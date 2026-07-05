#!/usr/bin/env python3
"""Tests for the PM MCP server's token-efficiency / ergonomics behavior
(2026-07-04, eng-blog backlog #2: concise/detailed modes, pagination,
actionable errors).

Runs against a THROWAWAY sqlite db (never the live one).

Run:  python3 mcp-servers/pm/test_server.py
Exits non-zero on any failure.
"""

import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="pm-test-")
DB = os.path.join(TMP, "test.db")
os.environ["PM_DB_PATH"] = DB  # must be set BEFORE importing server

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server  # noqa: E402

SCHEMA = """
CREATE TABLE items (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    owner TEXT NOT NULL,
    counterparty TEXT,
    description TEXT NOT NULL,
    context TEXT,
    source TEXT,
    source_date TEXT,
    due_date TEXT,
    wake_condition TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
    completed_at TEXT,
    template_id TEXT,
    external_ref TEXT
);
CREATE TABLE tags (
    item_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (item_id, tag)
);
"""

failures = []


def check(name, cond, detail=""):
    status = "ok" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def setup():
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    rows = [
        ("pm-000001", "task", "user", None, "Send Alice the roadmap plan",
         "Discussed in Monday 1:1", "session", today, yesterday, "open", "high", None),
        ("pm-000002", "task", "edwin", None, "Rotate the o365 credentials",
         None, "session", today, None, "open", None, "linear:BRA-9"),
        ("pm-000003", "intention", "user", "Carol", "Review CAB minutes",
         None, "session", today, today, "done", None, None),
    ]
    # 60 filler items so pm_list's default limit=50 truncates
    for i in range(4, 64):
        rows.append((f"pm-{i:06d}", "task", "edwin", None, f"Filler item number {i}",
                     None, "test", today, None, "open", None, None))
    conn.executemany(
        "INSERT INTO items (id, type, owner, counterparty, description, context, "
        "source, source_date, due_date, status, priority, external_ref) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def main():
    setup()

    # --- pm_list: invalid filter is an actionable error, not silent default --
    out = server.pm_list(filter="opne")
    check("pm_list rejects unknown filter", out.startswith("Error: unknown filter")
          and "open" in out, out)

    # --- pm_list: concise default has no context/source lines ---------------
    out = server.pm_list(filter="open", owner="user")
    check("pm_list concise omits context", "context:" not in out and "Send Alice" in out, out)

    # --- pm_list: detailed adds context/refs ---------------------------------
    out = server.pm_list(filter="open", owner="user", detail="detailed")
    check("pm_list detailed shows context", "context: Discussed in Monday 1:1" in out, out)
    out2 = server.pm_list(filter="open", owner="edwin", detail="detailed", limit=100)
    check("pm_list detailed shows external_ref", "external_ref: linear:BRA-9" in out2, out2)

    # --- pm_list: truncation footer + offset pagination ----------------------
    out = server.pm_list(filter="open")  # 62 open, default limit 50
    check("pm_list truncation footer", "showing 1-50 of 62" in out and "offset=50" in out, out)
    out = server.pm_list(filter="open", offset=50)
    check("pm_list offset page has remainder, no footer",
          out.count("[pm-") == 12 and "showing" not in out, out)

    # --- pm_list: empty result names the active filters ----------------------
    out = server.pm_list(filter="open", owner="nobody-here")
    check("pm_list empty names filters", "filter=open" in out and "owner=nobody-here" in out, out)

    # --- pm_list: bad detail value -------------------------------------------
    out = server.pm_list(detail="verbose")
    check("pm_list rejects bad detail", out.startswith("Error: detail"), out)

    # --- pm_search: hit works, footer works -----------------------------------
    out = server.pm_search("Filler item")
    check("pm_search truncation footer", "showing 1-20 of 60" in out and "offset=20" in out, out)
    out = server.pm_search("Filler item", offset=40)
    check("pm_search offset works", out.count("[pm-") == 20, out)

    # --- pm_search: empty result explains substring semantics -----------------
    out = server.pm_search("send the roadmap to alice")  # reworded -> no hit
    check("pm_search empty explains substring", "LITERAL substring" in out
          and "near-duplicate guard" in out, out)

    # --- pm_search: detailed --------------------------------------------------
    out = server.pm_search("roadmap", detail="detailed")
    check("pm_search detailed shows context", "context: Discussed in Monday 1:1" in out, out)

    # --- pm_complete / pm_update: actionable not-found ------------------------
    out = server.pm_complete("pm-zzzzzz")
    check("pm_complete not-found is actionable", "pm_search" in out and "pm_list" in out, out)
    out = server.pm_update("pm-zzzzzz", status="done")
    check("pm_update not-found is actionable", "pm_search" in out, out)

    # --- unchanged behavior spot-checks ---------------------------------------
    out = server.pm_complete("pm-000002")
    check("pm_complete still works", out.startswith("Completed [pm-000002]"), out)
    out = server.pm_list(filter="done", limit=100)
    check("done filter still works", "pm-000002" in out and "pm-000003" in out, out)

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S): {failures}")
        sys.exit(1)
    print("All PM server tests passed.")


if __name__ == "__main__":
    main()
