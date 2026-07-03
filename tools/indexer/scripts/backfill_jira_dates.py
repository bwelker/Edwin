#!/opt/homebrew/bin/python3.12
"""One-off: backfill the 'date' payload on jira points in Qdrant.

All 48,954 jira points were indexed without a 'date' payload (jira
frontmatter has created/updated, not 'date' -- extract_date only looked
for 'date' until 2026-07-02). This scrolls every jira point, derives the
date from the source file's frontmatter (updated > created, matching the
fixed lib/metadata.extract_date), and batch set_payload's it. No
re-embedding.

Usage:
    backfill_jira_dates.py            # do it
    backfill_jira_dates.py --dry-run  # report what would change
"""

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.config import QDRANT_URL, COLLECTION_NAME  # noqa: E402
from lib.metadata import extract_frontmatter, extract_date  # noqa: E402


def post(path, body):
    req = urllib.request.Request(
        f"{QDRANT_URL}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=120).read())


def main():
    dry_run = "--dry-run" in sys.argv

    # 1. Scroll all jira points missing a date payload
    print("Scrolling jira points...", file=sys.stderr)
    ids_by_file: dict[str, list] = {}
    already_dated = 0
    offset = None
    while True:
        body = {
            "filter": {"must": [{"key": "source", "match": {"value": "jira"}}]},
            "limit": 5000,
            "with_payload": ["file_path", "date"],
            "with_vector": False,
        }
        if offset is not None:
            body["offset"] = offset
        r = post(f"/collections/{COLLECTION_NAME}/points/scroll", body)["result"]
        for p in r["points"]:
            if p["payload"].get("date"):
                already_dated += 1
                continue
            fp = p["payload"].get("file_path")
            if fp:
                ids_by_file.setdefault(fp, []).append(p["id"])
        offset = r.get("next_page_offset")
        if offset is None:
            break
    n_points = sum(len(v) for v in ids_by_file.values())
    print(f"  {n_points} dateless points across {len(ids_by_file)} files "
          f"({already_dated} already dated)", file=sys.stderr)

    # 2. Derive each file's date from frontmatter (updated > created)
    ids_by_date: dict[str, list] = {}
    missing_file = 0
    no_date = 0
    for fp, ids in ids_by_file.items():
        path = Path(fp)
        if not path.exists():
            missing_file += 1
            continue
        content = path.read_text(errors="replace")
        d = extract_date(path, extract_frontmatter(content))
        if not d:
            no_date += 1
            continue
        ids_by_date.setdefault(d, []).extend(ids)

    n_settable = sum(len(v) for v in ids_by_date.values())
    print(f"  {n_settable} points get a date; "
          f"{missing_file} files gone from disk, {no_date} files with no "
          f"derivable date", file=sys.stderr)

    if dry_run:
        sample = sorted(ids_by_date.items())[:5]
        for d, ids in sample:
            print(f"    {d}: {len(ids)} points", file=sys.stderr)
        print("Dry run -- nothing written.", file=sys.stderr)
        return 0

    # 3. Batch set_payload, grouped by date value, chunks of 1000 ids
    done = 0
    for d, ids in sorted(ids_by_date.items()):
        for i in range(0, len(ids), 1000):
            batch = ids[i:i + 1000]
            post(f"/collections/{COLLECTION_NAME}/points/payload?wait=true",
                 {"payload": {"date": d}, "points": batch})
            done += len(batch)
            if done % 10000 < 1000:
                print(f"  set_payload: {done}/{n_settable}", file=sys.stderr)

    # 4. Verify
    r = post(f"/collections/{COLLECTION_NAME}/points/count",
             {"filter": {"must": [
                 {"key": "source", "match": {"value": "jira"}},
                 {"key": "date", "range": {"gte": "1900-01-01"}}]},
              "exact": True})
    print(f"Done: {done} points updated. Jira points with date payload now: "
          f"{r['result']['count']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
