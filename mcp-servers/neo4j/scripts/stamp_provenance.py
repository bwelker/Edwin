#!/usr/bin/env python3
"""
One-off provenance floor (A6, 2026-07-02).

Stamps source_ref="pre-provenance:2026-07-02-backup" on every relationship
that lacks a source_ref, so downstream queries can always rely on the property
existing. The value points at the rollback record
data/backups/neo4j-pre-downscope-2026-07-02.jsonl.

Idempotent -- re-running stamps nothing new. Run with the server venv:
    mcp-servers/neo4j/venv/bin/python mcp-servers/neo4j/scripts/stamp_provenance.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import PRE_PROVENANCE_REF, _get_neo4j_driver  # noqa: E402


def main():
    driver = _get_neo4j_driver()
    try:
        with driver.session() as session:
            total = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            missing_before = session.run(
                "MATCH ()-[r]->() WHERE r.source_ref IS NULL RETURN count(r) AS c"
            ).single()["c"]
            result = session.run(
                "MATCH ()-[r]->() WHERE r.source_ref IS NULL "
                "SET r.source_ref = $ref RETURN count(r) AS c",
                ref=PRE_PROVENANCE_REF,
            )
            stamped = result.single()["c"]
            missing_after = session.run(
                "MATCH ()-[r]->() WHERE r.source_ref IS NULL RETURN count(r) AS c"
            ).single()["c"]
        print(f"total edges:            {total}")
        print(f"missing source_ref:     {missing_before}")
        print(f"stamped this run:       {stamped} (-> {PRE_PROVENANCE_REF!r})")
        print(f"missing after:          {missing_after}")
        return 0 if missing_after == 0 else 1
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
