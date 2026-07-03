#!/usr/bin/env python3
"""Tests / demo for PM near-duplicate detection.

Proves the whole point of this change: a pair of REWORDED-but-identical
commitments that the literal pm_search substring matcher (SQL LIKE) does NOT
catch, but the fuzzy add-time guard DOES.

Run:  python3 tools/pm-dedup/test_dedup.py
Exits non-zero on any failure.
"""

import importlib.util
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dedup_core import DEFAULT_THRESHOLD, find_matches, similarity  # noqa: E402

# ---------------------------------------------------------------------------
# The demo pair: two phrasings of the SAME commitment.
# ---------------------------------------------------------------------------
EXISTING = "Email Jane Doe and John Roe with details on Sam's role change (support->implementation)"
REWORDED = "Send email to Jane Doe and John Roe with Sam's role change details -- moved from support (80k) to implementation"
DISTINCT = "Book the Q3 board dinner reservation at the downtown restaurant for the investor sync"

PASS, FAIL = 0, 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def substring_would_match(a, b):
    """Emulate pm_search: is either description a case-insensitive substring
    of the other? (That is all SQL LIKE '%q%' can do.)"""
    la, lb = a.lower(), b.lower()
    return la in lb or lb in la


print("== 1. Detection layer (dedup_core) ==")
score = similarity(EXISTING, REWORDED)
print(f"  similarity(existing, reworded) = {score:.3f} (threshold {DEFAULT_THRESHOLD})")
check("reworded dup scores at/above threshold", score >= DEFAULT_THRESHOLD)
check("SUBSTRING search MISSES the reworded dup (the bug we fix)",
      not substring_would_match(EXISTING, REWORDED))
check("genuinely distinct item scores below threshold",
      similarity(EXISTING, DISTINCT) < DEFAULT_THRESHOLD)

matches = find_matches(
    REWORDED,
    [{"id": "pm-existing", "description": EXISTING, "status": "open",
      "counterparty": "Jane Doe"}],
    counterparty="Jane Doe",
)
check("find_matches flags the open near-duplicate", len(matches) == 1)
check("find_matches mutates nothing (returns tuples only)",
      matches and isinstance(matches[0], tuple))

# ---------------------------------------------------------------------------
# 2. End-to-end: exercise the REAL pm_add guard against a throwaway DB.
# ---------------------------------------------------------------------------
print("\n== 2. End-to-end pm_add guard (real server, temp DB) ==")

SCHEMA = """
CREATE TABLE items (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, owner TEXT NOT NULL,
    counterparty TEXT, description TEXT NOT NULL, context TEXT, source TEXT,
    source_date TEXT, due_date TEXT, wake_condition TEXT,
    status TEXT NOT NULL DEFAULT 'open', priority TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
    completed_at TEXT, template_id TEXT, external_ref TEXT
);
CREATE TABLE tags (item_id TEXT, tag TEXT, PRIMARY KEY (item_id, tag));
"""

tmpdir = tempfile.mkdtemp(prefix="pm-dedup-test-")
db_path = Path(tmpdir) / "test.db"
conn = sqlite3.connect(str(db_path))
conn.executescript(SCHEMA)
conn.execute(
    "INSERT INTO items (id, type, owner, counterparty, description, status) "
    "VALUES ('pm-seed', 'task', 'user', 'Jane Doe', ?, 'open')",
    (EXISTING,),
)
conn.commit()
conn.close()

os.environ["PM_DB_PATH"] = str(db_path)
spec = importlib.util.spec_from_file_location(
    "pm_server_under_test", HERE.parents[1] / "mcp-servers" / "pm" / "server.py"
)
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

check("dedup guard is wired into the server", server._DEDUP_AVAILABLE is True)

# FastMCP may wrap the tool; unwrap to the plain callable if needed.
pm_add = getattr(server.pm_add, "fn", server.pm_add)

r1 = pm_add(REWORDED, counterparty="Jane Doe")
print(f"  add(reworded)        -> {r1.splitlines()[0]}")
check("reworded add is BLOCKED (not inserted)", "NOT added" in r1)
check("blocked message surfaces the candidate match", "pm-seed" in r1)

r2 = pm_add(REWORDED, counterparty="Jane Doe", force=True)
print(f"  add(reworded, force) -> {r2}")
check("force=True bypasses the guard and adds", r2.startswith("Added"))

r3 = pm_add(DISTINCT)
print(f"  add(distinct)        -> {r3}")
check("genuinely distinct item adds normally", r3.startswith("Added"))

# Confirm the seed item was never mutated by the guard (flag-only invariant).
conn = sqlite3.connect(str(db_path))
seed_status = conn.execute(
    "SELECT status FROM items WHERE id='pm-seed'"
).fetchone()[0]
n_items = conn.execute("SELECT count(*) FROM items").fetchone()[0]
conn.close()
check("guard never mutated the existing item (still open)", seed_status == "open")
check("only forced + distinct adds landed (seed + 2 = 3 rows)", n_items == 3)

print(f"\n{'='*50}\nRESULT: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
