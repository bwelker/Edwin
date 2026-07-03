#!/opt/homebrew/bin/python3.12
"""Indexer coverage check -- read-only audit of on-disk indexable markdown
vs what actually made it into Qdrant.

Answers two questions the state file (.index-state.json) cannot answer on
its own, because the state file records what the LAST sync run *believes*
it did, not what is actually sitting in Qdrant right now:

  1. Presence: of every file the scanner's whitelist/exclusion rules say
     should be indexed, how many have at least one point in Qdrant?
     Files with disk presence but zero Qdrant points are "missing" --
     never indexed, or their points were deleted/lost without the file
     being deleted.
  2. Context coverage: of the chunks that carry a Haiku context prefix
     requirement (per CONTEXT_SOURCE_THRESHOLDS / bulk-mail / oversized-doc
     rules), what fraction actually have a non-empty `context` payload?
     Reuses the classification logic already built for the RAG audit
     (scripts/reconcile_context.py) instead of re-deriving it.

This tool is READ-ONLY against Qdrant (scroll/count only) and does not
touch the state file or trigger any (re)indexing. It reports gaps; a human
or a separate job (indexer sync --backfill-context, a targeted --source
sync) decides what to do about them.

Usage:
    coverage_check                    # Full report, all sources, stdout
    coverage_check --source jira      # Limit to one source
    coverage_check --json             # Machine-readable report
    coverage_check --list-gaps 20     # Show up to N missing files/source
                                       # (default 5, 0 = suppress file lists)

Exit code: 0 if no missing files and no broken-context chunks found,
1 if either gap category is non-empty (for cron/CI wiring later), 2 on
a Qdrant connectivity error.

Caveat: this is a point-in-time snapshot taken with two separate,
non-transactional passes (an on-disk scan, then a Qdrant scroll) against a
collection connectors keep writing to (hourly sync runner, nightly context
backfill). Aggregate counts and per-source percentages are reliable; any
single file flagged "missing" can occasionally be a transient artifact of
a concurrent delete+reupsert landing mid-scroll. Re-run (or spot-check with
`indexer sync --dry-run --source <name>`) before acting on an individual
file rather than a source-level gap.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import DATA_DIR, MEMORY_DIR  # noqa: E402
from lib.metadata import detect_source  # noqa: E402
from lib.scanner import FileScanner  # noqa: E402
from lib.qdrant_store import QdrantStore  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reconcile_context as rc  # noqa: E402


# ---------------------------------------------------------------------------
# On-disk indexable set (ground truth: the scanner's own whitelist rules)
# ---------------------------------------------------------------------------

def on_disk_indexable(source_filter: str | None) -> dict[str, set[str]]:
    """Files the scanner's rules say should be indexed, keyed by source,
    valued as absolute-path strings (matching Qdrant's file_path payload).

    Uses FileScanner.scan(force=True), which applies every whitelist /
    exclusion rule (slice-subset dedup, photos skip, imessage/conversations
    skip, documents whitelist, filename
    patterns) but performs NO hashing and NO state writes -- force=True
    short-circuits straight to "include", and scan() never calls save().

    NOTE on source filtering: this tool's `--source` is a Qdrant *source
    name* (e.g. "o365-mail", "google-mail"), which is what the point's
    `source` payload holds and what qdrant_indexed_files / rc.collect match
    against. FileScanner.scan(source_filter=...) does NOT understand those
    names -- it substring-matches against on-disk path *tokens* (the first
    two path components, e.g. "o365", "mail"). Passing "o365-mail" there
    matches nothing, so the scan returned zero disk files and every indexed
    file was mislabeled an orphan. So we always run the FULL scan and bucket
    by detect_source() (which yields Qdrant names), then narrow to the
    requested source here -- keeping the disk side on the same naming
    convention as the Qdrant side. (A few Qdrant names, e.g. "jira",
    happen to be substrings of their path token and worked by accident;
    hyphenated ones like "o365-mail" did not.)
    """
    scanner = FileScanner()
    to_index, _to_delete = scanner.scan(force=True)
    by_source: dict[str, set[str]] = defaultdict(set)
    for p in to_index:
        src = detect_source(p)
        if source_filter and src != source_filter:
            continue
        by_source[src].add(str(p))
    return by_source


# ---------------------------------------------------------------------------
# Qdrant reality: distinct file_path values actually holding points
# ---------------------------------------------------------------------------

def qdrant_indexed_files(store: QdrantStore, source_filter: str | None) -> dict[str, set[str]]:
    """Distinct file_path values with >=1 point in Qdrant, keyed by source
    (from the point's own `source` payload -- ground truth as embedded,
    not re-derived from the path)."""
    by_source: dict[str, set[str]] = defaultdict(set)
    offset = None
    scroll_filter = None
    if source_filter:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        scroll_filter = Filter(must=[FieldCondition(
            key="source", match=MatchValue(value=source_filter))])
    while True:
        points, offset = store.client.scroll(
            collection_name=store.collection,
            scroll_filter=scroll_filter,
            limit=8192,
            with_payload=["file_path", "source"],
            with_vectors=False,
            offset=offset,
        )
        for pt in points:
            fp = pt.payload.get("file_path")
            src = pt.payload.get("source", "?")
            if fp:
                by_source[src].add(fp)
        if offset is None:
            break
    return by_source


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def build_report(source_filter: str | None) -> dict:
    store = QdrantStore()

    disk = on_disk_indexable(source_filter)
    qdrant = qdrant_indexed_files(store, source_filter)

    all_sources = sorted(set(disk) | set(qdrant))

    # Context coverage (chunk-level), reusing the RAG-audit classifier.
    broken, intentional, missing = rc.collect(source_filter)
    ctx_sources = sorted(set(broken) | set(intentional) | set(missing) | set(all_sources))
    total_chunks = rc.total_chunks_by_source(store, ctx_sources)

    per_source = {}
    g_disk = g_qdrant = g_missing_files = g_orphan_files = 0
    g_total_chunks = g_ctx_covered = g_ctx_required = g_broken_chunks = 0

    for src in sorted(set(all_sources) | set(ctx_sources)):
        disk_files = disk.get(src, set())
        qdrant_files = qdrant.get(src, set())
        missing_files = sorted(disk_files - qdrant_files)
        orphan_files = sorted(qdrant_files - disk_files)

        b = broken.get(src, {})
        i = intentional.get(src, {})
        m = missing.get(src, {})
        broken_chunks = sum(b.values())
        empty_chunks_total = broken_chunks + sum(i.values()) + sum(m.values())
        src_total_chunks = total_chunks.get(src, 0)
        ctx_covered = src_total_chunks - empty_chunks_total
        ctx_required = ctx_covered + broken_chunks  # excludes intentional/missing empties
        ctx_pct = (100.0 * ctx_covered / ctx_required) if ctx_required else 100.0
        file_pct = (100.0 * len(qdrant_files & disk_files) / len(disk_files)
                    ) if disk_files else (100.0 if not qdrant_files else 0.0)

        per_source[src] = {
            "disk_files": len(disk_files),
            "qdrant_files": len(qdrant_files & disk_files),
            "file_coverage_pct": round(file_pct, 1),
            "missing_files": missing_files,
            "orphan_files_count": len(orphan_files),
            "orphan_files": orphan_files,
            "total_chunks": src_total_chunks,
            "chunks_with_context": ctx_covered,
            "broken_context_chunks": broken_chunks,
            "broken_context_files": sorted(b),
            "context_coverage_pct": round(ctx_pct, 1),
        }

        g_disk += len(disk_files)
        g_qdrant += len(qdrant_files & disk_files)
        g_missing_files += len(missing_files)
        g_orphan_files += len(orphan_files)
        g_total_chunks += src_total_chunks
        g_ctx_covered += ctx_covered
        g_ctx_required += ctx_required
        g_broken_chunks += broken_chunks

    overall = {
        "disk_files": g_disk,
        "qdrant_files": g_qdrant,
        "file_coverage_pct": round(100.0 * g_qdrant / g_disk, 1) if g_disk else 100.0,
        "missing_files_total": g_missing_files,
        "orphan_files_total": g_orphan_files,
        "total_chunks": g_total_chunks,
        "chunks_with_context": g_ctx_covered,
        "broken_context_chunks": g_broken_chunks,
        "context_coverage_pct": round(100.0 * g_ctx_covered / g_ctx_required, 1)
                                 if g_ctx_required else 100.0,
    }

    return {"sources": per_source, "overall": overall}


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def print_report(report: dict, list_gaps: int):
    sources = report["sources"]
    overall = report["overall"]

    hdr = (f"{'source':<16} {'disk':>7} {'qdrant':>7} {'file_cov%':>9} "
           f"{'chunks':>8} {'ctx_cov%':>8} {'broken_chk':>10} {'orphans':>7}")
    print(hdr)
    print("-" * len(hdr))
    for src in sorted(sources):
        s = sources[src]
        if s["disk_files"] == 0 and s["qdrant_files"] == 0 and s["total_chunks"] == 0:
            continue
        print(f"{src:<16} {s['disk_files']:>7} {s['qdrant_files']:>7} "
              f"{s['file_coverage_pct']:>9.1f} {s['total_chunks']:>8} "
              f"{s['context_coverage_pct']:>8.1f} {s['broken_context_chunks']:>10} "
              f"{s['orphan_files_count']:>7}")
    print("-" * len(hdr))
    print(f"{'TOTAL':<16} {overall['disk_files']:>7} {overall['qdrant_files']:>7} "
          f"{overall['file_coverage_pct']:>9.1f} {overall['total_chunks']:>8} "
          f"{overall['context_coverage_pct']:>8.1f} {overall['broken_context_chunks']:>10} "
          f"{overall['orphan_files_total']:>7}")

    print(f"\nMissing (on disk, indexable, zero Qdrant points): "
          f"{overall['missing_files_total']}")
    print(f"Orphaned (Qdrant points, no longer indexable on disk): "
          f"{overall['orphan_files_total']}")
    print(f"Broken-context chunks (source requires Haiku context, chunk has "
          f"none): {overall['broken_context_chunks']}")

    if list_gaps > 0:
        for src in sorted(sources):
            s = sources[src]
            if s["missing_files"]:
                print(f"\n  [{src}] missing files ({len(s['missing_files'])}):")
                for f in s["missing_files"][:list_gaps]:
                    print(f"    {f}")
                if len(s["missing_files"]) > list_gaps:
                    print(f"    ... and {len(s['missing_files']) - list_gaps} more")
            if s["broken_context_files"]:
                print(f"\n  [{src}] broken-context files ({len(s['broken_context_files'])}):")
                for f in s["broken_context_files"][:list_gaps]:
                    print(f"    {f}")
                if len(s["broken_context_files"]) > list_gaps:
                    print(f"    ... and {len(s['broken_context_files']) - list_gaps} more")

    print("\nRead-only report. No files were re-indexed. To close gaps:")
    print("  indexer sync --source <name>              # missing files")
    print("  indexer sync --backfill-context            # broken-context files "
          "(after scripts/reconcile_context.py reset)")
    print("\nNote: point-in-time snapshot against a live, continuously-synced "
          "collection. Source-level percentages are reliable; re-run before "
          "acting on a single flagged file (see module docstring).")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", default=None, help="Limit to one source type")
    ap.add_argument("--json", action="store_true", help="Machine-readable output")
    ap.add_argument("--list-gaps", type=int, default=5,
                     help="Max gap files to list per source per category "
                          "(default 5, 0 = suppress)")
    args = ap.parse_args()

    try:
        report = build_report(args.source)
    except SystemExit:
        # QdrantStore already logged the connection error.
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report, args.list_gaps)

    overall = report["overall"]
    if overall["missing_files_total"] or overall["broken_context_chunks"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
