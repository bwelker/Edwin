#!/opt/homebrew/bin/python3.12
"""Prune already-indexed points from Qdrant for files that are no longer
eligible for indexing (e.g. after adding a scanner exclusion), and remove
their state-file entries so they don't resurrect on the next sync.

Selection (either or both):
    --path-prefix PREFIX   state keys starting with PREFIX (relative to
                           data/, e.g. "imessage/conversations/"; use the
                           "@memory/" prefix for memory-root keys).
                           Repeatable.
    --paths-file FILE      newline-separated list of ABSOLUTE file paths
                           or data/-relative state keys to prune.

Modes:
    --dry-run              report what WOULD be deleted (default: real run)

Deletes points by exact file_path payload match (same mechanism the
indexer's own delete path uses), then removes the state entries via the
scanner's lock-protected merge-save. Prints collection point counts
before/after for verification.

Usage:
    prune_source.py --path-prefix imessage/conversations/ --dry-run
    prune_source.py --path-prefix imessage/conversations/
    prune_source.py --paths-file /tmp/subset-slices.txt
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.scanner import FileScanner, key_to_path  # noqa: E402
from lib.qdrant_store import QdrantStore  # noqa: E402
from lib.config import DATA_DIR  # noqa: E402

from qdrant_client.models import Filter, FieldCondition, MatchValue  # noqa: E402


def count_points_for_path(store: QdrantStore, file_path: str) -> int:
    return store.client.count(
        collection_name=store.collection,
        count_filter=Filter(must=[FieldCondition(
            key="file_path", match=MatchValue(value=file_path))]),
        exact=True,
    ).count


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--path-prefix", action="append", default=[],
                    help="state-key prefix to prune (repeatable)")
    ap.add_argument("--paths-file",
                    help="file with newline-separated paths/keys to prune")
    ap.add_argument("--dry-run", action="store_true",
                    help="report only, delete nothing")
    args = ap.parse_args()

    if not args.path_prefix and not args.paths_file:
        ap.error("need --path-prefix and/or --paths-file")

    scanner = FileScanner()
    state_files = scanner.state.get("files", {})

    # -- Select state keys ---------------------------------------------------
    selected: set[str] = set()
    for prefix in args.path_prefix:
        selected.update(k for k in state_files if k.startswith(prefix))

    explicit_untracked: list[str] = []
    if args.paths_file:
        for line in Path(args.paths_file).read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("/"):  # absolute path -> state key
                p = Path(line)
                try:
                    key = str(p.relative_to(DATA_DIR))
                except ValueError:
                    key = line
            else:
                key = line
            if key in state_files:
                selected.add(key)
            else:
                explicit_untracked.append(key)

    if not selected and not explicit_untracked:
        print("Nothing matches -- no state entries selected.")
        return 0

    state_chunks = sum(state_files[k].get("chunks", 0) for k in selected)
    print(f"Selected {len(selected)} tracked files "
          f"({state_chunks} chunks per state file)")
    if explicit_untracked:
        print(f"  ({len(explicit_untracked)} listed paths not in state -- "
              f"never indexed, skipping)")
    for k in sorted(selected)[:10]:
        print(f"    {k}")
    if len(selected) > 10:
        print(f"    ... and {len(selected) - 10} more")

    # -- Count actual points -------------------------------------------------
    store = QdrantStore()
    before_total = store.client.count(
        collection_name=store.collection, exact=True).count
    print(f"\nCollection points before: {before_total}")

    point_counts = {}
    for k in sorted(selected):
        fp = str(key_to_path(k))
        point_counts[k] = count_points_for_path(store, fp)
    total_points = sum(point_counts.values())
    zero = sum(1 for v in point_counts.values() if v == 0)
    print(f"Points matching selected files: {total_points} "
          f"({zero} files have 0 points)")

    if args.dry_run:
        print(f"\nDRY RUN: would delete {total_points} points and "
              f"{len(selected)} state entries.")
        return 0

    # -- Delete --------------------------------------------------------------
    print(f"\nDeleting {total_points} points across {len(selected)} files...")
    for i, k in enumerate(sorted(selected), 1):
        store.delete_file_points(str(key_to_path(k)))
        scanner.remove_file(k)
        if i % 200 == 0:
            print(f"  [{i}/{len(selected)}]")
    scanner.save()

    after_total = store.client.count(
        collection_name=store.collection, exact=True).count
    print(f"\nCollection points after: {after_total} "
          f"(delta {after_total - before_total:+d}, expected -{total_points})")
    print(f"State entries removed: {len(selected)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
