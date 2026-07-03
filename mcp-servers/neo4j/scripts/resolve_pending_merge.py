#!/usr/bin/env python3
"""
Drain the pending-merge queue.

kg_add_entity queues ambiguous name matches (similarity 0.75-0.96) to
data/kg/pending-merges.jsonl instead of creating or merging. This helper is
how nightwatch / the user resolve those entries:

    # See the queue with line numbers
    venv/bin/python scripts/resolve_pending_merge.py list

    # Resolve line N
    venv/bin/python scripts/resolve_pending_merge.py resolve <line> same
    venv/bin/python scripts/resolve_pending_merge.py resolve <line> different

Verdict SAME:
  - If a graph node exists with the candidate name (and isn't the existing
    node), its edges are COPIED onto the existing node and the originals
    invalidated (A6 conventions: invalid_at + reason, facts never deleted);
    the duplicate node is stamped merged_into=<existing_uuid> and its summary
    appended to the survivor.
  - If no candidate node exists (the normal case -- kg_add_entity created
    nothing), the queued candidate_summary is appended to the existing node.
  - The candidate name is written into the identity registry as a name alias
    of the person who owns the existing node (found via its neo4j_uuid alias),
    so the same ambiguity never queues twice.

Verdict DIFFERENT:
  - Nothing changes in the graph; the entry is recorded with its verdict so
    the decision is durable.

Either way the entry moves from pending-merges.jsonl to
pending-merges-resolved.jsonl with verdict + resolved_at stamped.
"""

import argparse
import json
import sqlite3
import sys
import uuid as uuid_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import (  # noqa: E402
    PENDING_MERGES_FILE,
    REGISTRY_DB,
    RESOLVED_MERGES_FILE,
    _get_neo4j_driver,
    _utc_now_iso,
)


def _load_queue() -> list[dict]:
    if not PENDING_MERGES_FILE.exists():
        return []
    entries = []
    for line in PENDING_MERGES_FILE.read_text().splitlines():
        line = line.strip()
        if line:
            entries.append(json.loads(line))
    return entries


def _registry_alias_for_merge(existing_uuid: str, candidate_name: str) -> str:
    """Write candidate_name as a name alias of the registry person linked to
    existing_uuid. Returns a status string for the report."""
    if not REGISTRY_DB.exists():
        return "registry DB not found -- alias not written"
    conn = sqlite3.connect(str(REGISTRY_DB))
    conn.row_factory = sqlite3.Row
    try:
        owner = conn.execute(
            "SELECT canonical_id FROM aliases WHERE alias_type = 'neo4j_uuid' AND alias_value = ?",
            (existing_uuid,),
        ).fetchone()
        if not owner:
            return f"no registry person linked to graph node {existing_uuid} -- name alias not written (run link_identity_registry.py first)"
        cur = conn.execute(
            "INSERT OR IGNORE INTO aliases (canonical_id, alias_type, alias_value, source) "
            "VALUES (?, 'name', ?, 'pending-merge-resolution')",
            (owner["canonical_id"], candidate_name),
        )
        conn.commit()
        if cur.rowcount:
            return f"name alias {candidate_name!r} added to registry person {owner['canonical_id']}"
        return f"name alias {candidate_name!r} already in registry"
    finally:
        conn.close()


def _merge_same(entry: dict) -> list[str]:
    """Apply a SAME verdict in the graph. Returns report lines."""
    report = []
    existing_uuid = entry["existing_uuid"]
    candidate_name = entry["candidate_name"]
    now_iso = _utc_now_iso()

    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            survivor = session.run(
                "MATCH (n:Entity {uuid: $uuid}) RETURN n.uuid AS uuid, n.name AS name",
                uuid=existing_uuid,
            ).single()
            if not survivor:
                raise SystemExit(f"Existing entity {existing_uuid} not found in graph -- aborting, queue untouched.")

            # Is there a separate node carrying the candidate name?
            dupes = [
                r["uuid"]
                for r in session.run(
                    "MATCH (n:Entity) WHERE toLower(n.name) = toLower($name) "
                    "AND n.uuid <> $survivor RETURN n.uuid AS uuid",
                    name=candidate_name.strip(), survivor=existing_uuid,
                )
            ]

            for dupe_uuid in dupes:
                # Copy each edge onto the survivor, then invalidate the original.
                edges = list(session.run(
                    "MATCH (d:Entity {uuid: $dupe})-[r]-(other:Entity) "
                    "WHERE other.uuid <> $survivor "
                    "RETURN elementId(r) AS eid, type(r) AS rel_type, properties(r) AS props, "
                    "other.uuid AS other_uuid, startNode(r).uuid = $dupe AS outgoing",
                    dupe=dupe_uuid, survivor=existing_uuid,
                ))
                copied = 0
                for e in edges:
                    props = dict(e["props"])
                    old_uuid = props.get("uuid") or str(uuid_module.uuid4())
                    props["uuid"] = str(uuid_module.uuid4())
                    props["merge_copied_from"] = old_uuid
                    if e["outgoing"]:
                        pattern = "MATCH (a:Entity {uuid: $survivor}), (b:Entity {uuid: $other}) CREATE (a)-[r:%s]->(b) SET r = $props"
                    else:
                        pattern = "MATCH (a:Entity {uuid: $survivor}), (b:Entity {uuid: $other}) CREATE (b)-[r:%s]->(a) SET r = $props"
                    session.run(pattern % e["rel_type"], survivor=existing_uuid, other=e["other_uuid"], props=props)
                    session.run(
                        "MATCH ()-[r]-() WHERE elementId(r) = $eid AND r.invalid_at IS NULL "
                        "SET r.uuid = $old_uuid, r.invalid_at = datetime($now), "
                        "r.invalidation_reason = $reason",
                        eid=e["eid"], old_uuid=old_uuid, now=now_iso,
                        reason=f"entity merged into {existing_uuid} (pending-merge verdict: same)",
                    )
                    copied += 1
                # Fold the duplicate's summary into the survivor, stamp the tombstone.
                session.run(
                    "MATCH (d:Entity {uuid: $dupe}), (s:Entity {uuid: $survivor}) "
                    "SET s.summary = CASE WHEN d.summary IS NULL OR d.summary = '' THEN s.summary "
                    "WHEN s.summary IS NULL OR s.summary = '' THEN d.summary "
                    "ELSE s.summary + '\n' + d.summary END, "
                    "d.merged_into = $survivor, d.merged_at = datetime($now)",
                    dupe=dupe_uuid, survivor=existing_uuid, now=now_iso,
                )
                report.append(f"merged duplicate node {dupe_uuid} into {existing_uuid}: {copied} edges copied+invalidated, summary folded, tombstone stamped")

            if not dupes:
                # Normal case: candidate was never created; append its queued summary.
                add = f"[{entry.get('date', '?')}, {entry.get('source_ref', 'pending-merge')}] {entry.get('candidate_summary', '').strip()}"
                session.run(
                    "MATCH (n:Entity {uuid: $uuid}) "
                    "SET n.summary = CASE WHEN n.summary IS NULL OR n.summary = '' "
                    "THEN $add ELSE n.summary + '\n' + $add END",
                    uuid=existing_uuid, add=add,
                )
                report.append(f"no separate candidate node; queued summary appended to {survivor['name']!r} ({existing_uuid})")
    finally:
        driver.close()

    report.append(_registry_alias_for_merge(existing_uuid, candidate_name))
    return report


def resolve_pending_merge(entry: dict, verdict: str) -> list[str]:
    """Resolve one queue entry. verdict is 'same' or 'different'.
    Applies graph/registry effects, then moves the entry to the resolved file."""
    if verdict == "same":
        report = _merge_same(entry)
    else:
        report = ["recorded as different entities; graph untouched"]

    entry_out = {**entry, "verdict": verdict, "resolved_at": _utc_now_iso()}
    RESOLVED_MERGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RESOLVED_MERGES_FILE, "a") as f:
        f.write(json.dumps(entry_out) + "\n")

    # Rewrite the queue without this entry.
    remaining = [e for e in _load_queue() if e != entry]
    PENDING_MERGES_FILE.write_text("".join(json.dumps(e) + "\n" for e in remaining))
    report.append(f"entry moved to {RESOLVED_MERGES_FILE.name}; {len(remaining)} still queued")
    return report


def main():
    parser = argparse.ArgumentParser(description="Resolve pending-merge queue entries")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="Show queued entries with line numbers")
    p = sub.add_parser("resolve", help="Resolve one entry by line number")
    p.add_argument("line", type=int, help="1-based line number from 'list'")
    p.add_argument("verdict", choices=["same", "different"])
    args = parser.parse_args()

    queue = _load_queue()
    if args.command == "list":
        if not queue:
            print("Queue is empty.")
            return
        for i, e in enumerate(queue, 1):
            print(f"{i}. {e['candidate_name']!r} vs {e['existing_name']!r} "
                  f"(sim {e.get('similarity_signal')}, {e.get('date')}, src: {e.get('source_ref')})")
        return

    if not 1 <= args.line <= len(queue):
        print(f"Line {args.line} out of range (queue has {len(queue)} entries).", file=sys.stderr)
        sys.exit(1)
    entry = queue[args.line - 1]
    print(f"Resolving: {entry['candidate_name']!r} vs {entry['existing_name']!r} -> {args.verdict}")
    for line in resolve_pending_merge(entry, args.verdict):
        print(f"  {line}")


if __name__ == "__main__":
    main()
