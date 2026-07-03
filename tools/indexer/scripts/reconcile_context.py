#!/opt/homebrew/bin/python3.12
"""Context-reality reconciliation (RAG audit 2026-07-02, finding F3b).

Chunks are supposed to carry Haiku context prefixes per
CONTEXT_SOURCE_THRESHOLDS, but the state file's context_done flag diverged
from index reality: files indexed before the per-source thresholds existed
(and files re-indexed while the flag "never downgraded") sit in Qdrant with
empty `context` payloads while the state says done, so --backfill-context
never touches them.

Commands:
    survey [--source X]         Scroll Qdrant for empty-context chunks,
                                classify per file as BROKEN (threshold
                                demands context) vs INTENTIONAL (bulk mail,
                                below threshold, oversized doc) vs MISSING
                                (file gone from disk). Read-only, safe to
                                run alongside a live sync. Prints a
                                per-source table + Haiku cost estimate.
    reset [--source X] [--limit N] [--dry-run]
                                Flip context_done -> False in the state file
                                for BROKEN files so `indexer sync
                                --backfill-context` picks them up.
                                Idempotent; state-file writes go through the
                                scanner's lock-protected dirty-key merge-
                                save, so a concurrently running sync is not
                                clobbered (and, with the dirty-key save fix,
                                does not clobber us).
    status                      Reconciliation progress: broken-and-pending
                                (queued for backfill) vs broken-but-flagged-
                                done (still needs reset) per source.

Cost model: conservative $4 per 1,000 chunks (Haiku 4.5, document sent as a
prompt-cached system message, ~100 output tokens per chunk). Real cost is
usually lower because segment-context sources send a segment, not the file.

NOTE on a concurrently RUNNING sync started before the dirty-key save fix
landed: its checkpoint saves assert its full stale snapshot and can revert
resets. The nightly sys-context-backfill pipeline re-runs `reset` before
every backfill, so reverted flips self-heal the next night.
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import (CONTEXT_SOURCE_THRESHOLDS, CONTEXT_MIN_DOC_TOKENS,
                        CONTEXT_SEGMENT_SOURCES, CHARS_PER_TOKEN,
                        DATA_DIR, MEMORY_DIR)  # noqa: E402
from lib.scanner import FileScanner, path_to_key  # noqa: E402
from lib.qdrant_store import QdrantStore  # noqa: E402
from lib.context import BULK_MAIL_SOURCES  # noqa: E402
from lib.bulkmail import is_bulk_mail  # noqa: E402
from lib.metadata import extract_frontmatter  # noqa: E402

from qdrant_client.models import (Filter, FieldCondition, MatchValue,  # noqa: E402
                                  IsEmptyCondition, PayloadField)

# Mirrors the oversized-document guard in lib/context.py (intentional skip).
MAX_DOC_CHARS = 180_000 * 3

# Conservative Haiku 4.5 estimate, dollars per context call (= per chunk).
COST_PER_CHUNK = 0.004

EMPTY_CONTEXT_FILTER = Filter(should=[
    # context stored as "" (indexer keeps empty strings in the payload)
    FieldCondition(key="context", match=MatchValue(value="")),
    # or the key is absent entirely (points from before context existed)
    IsEmptyCondition(is_empty=PayloadField(key="context")),
])


def scroll_empty_context(store: QdrantStore):
    """Yield (source, file_path) for every chunk with an empty/absent
    context payload. Read-only scroll; safe alongside a live sync."""
    offset = None
    while True:
        points, offset = store.client.scroll(
            collection_name=store.collection,
            scroll_filter=EMPTY_CONTEXT_FILTER,
            limit=4096,
            with_payload=["source", "file_path"],
            with_vectors=False,
            offset=offset,
        )
        for pt in points:
            yield (pt.payload.get("source", "?"),
                   pt.payload.get("file_path", ""))
        if offset is None:
            break


def classify_file(source: str, file_path: str) -> str:
    """Classify one empty-context file.

    Returns one of:
      "broken"      threshold demands context but the index has none
      "intentional" empty context is CORRECT (bulk mail / below threshold /
                    oversized doc) -- must NOT be re-queued
      "missing"     file no longer on disk (next sync deletes its points)
    """
    p = Path(file_path)
    try:
        size = p.stat().st_size
    except OSError:
        return "missing"

    threshold = CONTEXT_SOURCE_THRESHOLDS.get(source, CONTEXT_MIN_DOC_TOKENS)

    needs_text = (
        threshold > 0                     # threshold check needs char count
        or source in BULK_MAIL_SOURCES    # bulk classifier needs fm + body
        or size > MAX_DOC_CHARS           # exact char count near the cap
    )
    if not needs_text:
        return "broken"  # zero-threshold source, normal-sized file

    try:
        text = p.read_text(errors="replace")
    except OSError:
        return "missing"

    if threshold > 0 and len(text) < threshold * CHARS_PER_TOKEN:
        return "intentional"  # below per-source size threshold

    if len(text) > MAX_DOC_CHARS and source not in CONTEXT_SEGMENT_SOURCES:
        return "intentional"  # oversized-document guard skips context

    if source in BULK_MAIL_SOURCES:
        if is_bulk_mail(extract_frontmatter(text), text):
            return "intentional"  # bulk mail never gets paid context

    return "broken"


def collect(source_filter: str | None):
    """Scan Qdrant + disk. Returns per-source dicts:
        broken[source]      -> {file_path: empty_chunk_count}
        intentional[source] -> {file_path: empty_chunk_count}
        missing[source]     -> {file_path: empty_chunk_count}
    """
    store = QdrantStore()
    per_file: dict[tuple[str, str], int] = defaultdict(int)
    for source, file_path in scroll_empty_context(store):
        if source_filter and source != source_filter:
            continue
        if not file_path:
            continue
        per_file[(source, file_path)] += 1

    broken: dict[str, dict[str, int]] = defaultdict(dict)
    intentional: dict[str, dict[str, int]] = defaultdict(dict)
    missing: dict[str, dict[str, int]] = defaultdict(dict)
    buckets = {"broken": broken, "intentional": intentional,
               "missing": missing}
    for (source, file_path), n in per_file.items():
        buckets[classify_file(source, file_path)][source][file_path] = n
    return broken, intentional, missing


def total_chunks_by_source(store: QdrantStore, sources: list[str]) -> dict:
    out = {}
    for src in sources:
        out[src] = store.client.count(
            collection_name=store.collection,
            count_filter=Filter(must=[FieldCondition(
                key="source", match=MatchValue(value=src))]),
            exact=True,
        ).count
    return out


def state_key_for(file_path: str) -> str | None:
    """Map an absolute file_path payload to its state-file key."""
    p = Path(file_path)
    try:
        return path_to_key(p)          # handles @memory/ prefix
    except ValueError:
        pass
    try:
        return str(p.relative_to(DATA_DIR))
    except ValueError:
        return None


# ---------------------------------------------------------------------------

def cmd_survey(args) -> int:
    broken, intentional, missing = collect(args.source)
    store = QdrantStore()
    sources = sorted(set(broken) | set(intentional) | set(missing))
    totals = total_chunks_by_source(store, sources)

    hdr = (f"{'source':<16} {'total_chk':>9} {'empty_chk':>9} "
           f"{'broken_files':>12} {'broken_chk':>10} {'intent_files':>12} "
           f"{'missing':>7} {'est_cost':>9}")
    print(hdr)
    print("-" * len(hdr))
    g_bf = g_bc = g_cost = 0.0
    for src in sources:
        b = broken.get(src, {})
        i = intentional.get(src, {})
        m = missing.get(src, {})
        empty_chk = (sum(b.values()) + sum(i.values()) + sum(m.values()))
        bc = sum(b.values())
        cost = bc * COST_PER_CHUNK
        g_bf += len(b); g_bc += bc; g_cost += cost
        print(f"{src:<16} {totals.get(src, 0):>9} {empty_chk:>9} "
              f"{len(b):>12} {bc:>10} {len(i):>12} {len(m):>7} "
              f"${cost:>8,.2f}")
    print("-" * len(hdr))
    print(f"{'TOTAL broken':<16} {'':>9} {'':>9} {int(g_bf):>12} "
          f"{int(g_bc):>10} {'':>12} {'':>7} ${g_cost:>8,.2f}")
    print(f"\nCost model: ${COST_PER_CHUNK}/chunk (conservative; prompt-"
          f"cached Haiku). 'intent_files' = empty context is CORRECT "
          f"(bulk mail / below threshold / oversized) -- not re-queued.")
    return 0


def cmd_reset(args) -> int:
    broken, _, _ = collect(args.source)
    scanner = FileScanner()
    state_files = scanner.state.get("files", {})

    # Deterministic order; --limit caps how many files get flipped.
    candidates = []
    for src in sorted(broken):
        for fp in sorted(broken[src]):
            candidates.append((src, fp))

    flipped, already_pending, untracked = [], 0, 0
    for src, fp in candidates:
        if args.limit is not None and len(flipped) >= args.limit:
            break
        key = state_key_for(fp)
        if key is None or key not in state_files:
            untracked += 1
            continue
        if not state_files[key].get("context_done", False):
            already_pending += 1
            continue
        flipped.append(key)

    print(f"Broken files found: {len(candidates)}")
    print(f"  already pending (context_done=False): {already_pending}")
    print(f"  untracked in state (skipped):         {untracked}")
    print(f"  to flip context_done -> False:        {len(flipped)}"
          + (f" (limit {args.limit})" if args.limit is not None else ""))
    for k in flipped[:8]:
        print(f"    {k}")
    if len(flipped) > 8:
        print(f"    ... and {len(flipped) - 8} more")

    if args.dry_run:
        print("\nDRY RUN: state file not modified.")
        return 0
    if not flipped:
        print("\nNothing to flip.")
        return 0

    for key in flipped:
        scanner.set_context_pending(key)
    scanner.save()  # lock-protected, dirty-key merge -- only our flips win
    print(f"\nFlipped {len(flipped)} state entries. "
          f"`indexer sync --backfill-context` will regenerate their context.")
    return 0


def cmd_status(args) -> int:
    broken, intentional, missing = collect(args.source)
    scanner = FileScanner()
    state_files = scanner.state.get("files", {})

    print(f"{'source':<16} {'broken':>7} {'queued':>7} {'needs_reset':>12}")
    print("-" * 46)
    for src in sorted(broken):
        queued = needs_reset = 0
        for fp in broken[src]:
            key = state_key_for(fp)
            entry = state_files.get(key or "", {})
            if entry.get("context_done", False):
                needs_reset += 1
            else:
                queued += 1
        print(f"{src:<16} {len(broken[src]):>7} {queued:>7} {needs_reset:>12}")

    pending_total = sum(1 for e in state_files.values()
                        if not e.get("context_done", False))
    print(f"\nState entries with context_done=False (whole backfill queue, "
          f"all reasons): {pending_total}")
    print("'queued' broken files clear as nightly sys-context-backfill runs; "
          "'needs_reset' need another `reset` pass.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("survey", help="Read-only Qdrant coverage survey")
    p.add_argument("--source", default=None, help="Limit to one source type")

    p = sub.add_parser("reset", help="Flip context_done=False for broken files")
    p.add_argument("--source", default=None, help="Limit to one source type")
    p.add_argument("--limit", type=int, default=None,
                   help="Max files to flip this run")
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("status", help="Reconciliation progress")
    p.add_argument("--source", default=None, help="Limit to one source type")

    args = ap.parse_args()
    return {"survey": cmd_survey, "reset": cmd_reset,
            "status": cmd_status}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
