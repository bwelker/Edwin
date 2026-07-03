#!/usr/bin/env python3
"""
Identity-registry <-> knowledge-graph backfill (backlog item 7, 2026-07-02).

Walks every :Person entity in the Neo4j graph, resolves its name against the
identity registry (exact case-insensitive name-alias match, category='person'),
and for confident single-candidate matches writes the graph node's uuid into
the registry as a neo4j_uuid alias. This makes the registry the authority for
person-node identity: the kg_add_entity write path short-circuits to linked
nodes before any string-similarity tiers run.

Buckets reported:
  linked          -- neo4j_uuid alias written this run
  already-linked  -- alias was already present (idempotent re-runs land here)
  no-match        -- graph person unknown to the registry (listed; NOT auto-created)
  ambiguous       -- multiple registry people share the name (listed; skipped)
  conflict        -- registry person already linked to a DIFFERENT graph node,
                     or this uuid already registered to a different person
                     (listed; skipped -- likely graph duplicates to merge)

Idempotent -- safe to re-run. Run with the server venv:
    mcp-servers/neo4j/venv/bin/python mcp-servers/neo4j/scripts/link_identity_registry.py [--dry-run]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import REGISTRY_DB, _get_neo4j_driver  # noqa: E402

ALIAS_SOURCE = "kg-backfill"


def main():
    parser = argparse.ArgumentParser(description="Link graph :Person nodes to the identity registry")
    parser.add_argument("--dry-run", action="store_true", help="Report only; write nothing")
    args = parser.parse_args()

    if not REGISTRY_DB.exists():
        print(f"Registry DB not found: {REGISTRY_DB}", file=sys.stderr)
        sys.exit(1)

    reg = sqlite3.connect(str(REGISTRY_DB))
    reg.row_factory = sqlite3.Row

    driver = _get_neo4j_driver()
    with driver.session() as session:
        persons = [
            {"uuid": r["uuid"], "name": r["name"]}
            for r in session.run(
                "MATCH (n:Person) RETURN n.uuid AS uuid, n.name AS name ORDER BY n.name"
            )
            if r["uuid"] and r["name"]
        ]
    driver.close()

    linked, already, no_match, ambiguous, conflict = [], [], [], [], []

    for node in persons:
        # Who already owns this uuid, if anyone?
        uuid_owner = reg.execute(
            "SELECT canonical_id FROM aliases WHERE alias_type = 'neo4j_uuid' AND alias_value = ?",
            (node["uuid"],),
        ).fetchone()

        candidates = reg.execute(
            "SELECT DISTINCT p.id, p.display_name "
            "FROM aliases a JOIN canonical_people p ON a.canonical_id = p.id "
            "WHERE a.alias_type = 'name' AND a.alias_value = ? COLLATE NOCASE "
            "AND p.category = 'person'",
            (node["name"].strip(),),
        ).fetchall()

        if len(candidates) == 0:
            no_match.append(node)
            continue
        if len(candidates) > 1:
            ambiguous.append({**node, "candidates": [f"{c['id']}:{c['display_name']}" for c in candidates]})
            continue

        person = candidates[0]

        if uuid_owner and uuid_owner["canonical_id"] != person["id"]:
            conflict.append({**node, "reason": f"uuid already registered to person {uuid_owner['canonical_id']}, name resolves to {person['id']}"})
            continue
        if uuid_owner:  # owned by the right person
            already.append({**node, "person_id": person["id"]})
            continue

        existing_uuids = [
            r["alias_value"]
            for r in reg.execute(
                "SELECT alias_value FROM aliases WHERE canonical_id = ? AND alias_type = 'neo4j_uuid'",
                (person["id"],),
            )
        ]
        if existing_uuids:
            conflict.append({**node, "reason": f"person {person['id']} ({person['display_name']}) already linked to graph node(s) {existing_uuids} -- likely graph duplicates, merge in the graph first"})
            continue

        if not args.dry_run:
            reg.execute(
                "INSERT OR IGNORE INTO aliases (canonical_id, alias_type, alias_value, source) "
                "VALUES (?, 'neo4j_uuid', ?, ?)",
                (person["id"], node["uuid"], ALIAS_SOURCE),
            )
        linked.append({**node, "person_id": person["id"], "person_name": person["display_name"]})

    if not args.dry_run:
        reg.commit()
    reg.close()

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}Graph :Person nodes: {len(persons)}")
    print(f"  linked:         {len(linked)}")
    print(f"  already-linked: {len(already)}")
    print(f"  no-match:       {len(no_match)}")
    print(f"  ambiguous:      {len(ambiguous)}")
    print(f"  conflict:       {len(conflict)}")

    if no_match:
        print("\nNo registry match (graph person unknown to registry -- NOT auto-created):")
        for n in no_match:
            print(f"  {n['uuid']}  {n['name']}")
    if ambiguous:
        print("\nAmbiguous (multiple registry candidates -- skipped):")
        for n in ambiguous:
            print(f"  {n['uuid']}  {n['name']}  candidates: {', '.join(n['candidates'])}")
    if conflict:
        print("\nConflicts (skipped):")
        for n in conflict:
            print(f"  {n['uuid']}  {n['name']}  {n['reason']}")


if __name__ == "__main__":
    main()
