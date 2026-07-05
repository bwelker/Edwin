#!/usr/bin/env python3
"""Regression tests for budget-watch, anchored on the 2026-07-04 false-alert
batches (pm-be92ff).

Root causes reproduced here:
  1. Streaming duplicates the same usage block across multiple assistant
     JSONL entries of one API message -> per-entry summing over-counted
     fresh tokens ~2-3x (agents read as 1.45-1.58M fresh; true burn ~600K).
  2. Completed task transcripts still inside the active-mtime window kept
     alerting; the watcher now reads the harness task-notification status
     from the parent session transcript and skips finished tasks.
  3. A static (non-growing) breach re-alerted every interval.

Run: python3 tools/budget-watch/test_budget_watch.py
"""

import importlib.util
import importlib.machinery
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BW = HERE / "budget-watch"

loader = importlib.machinery.SourceFileLoader("budget_watch", str(BW))
spec = importlib.util.spec_from_loader("budget_watch", loader)
bw = importlib.util.module_from_spec(spec)
loader.exec_module(bw)


def _entry(mid, i=100, cc=200, cr=1000, o=50, ts="2026-07-04T22:00:00.000Z"):
    return json.dumps({
        "type": "assistant", "timestamp": ts,
        "message": {"id": mid, "model": "claude-opus-4",
                    "usage": {"input_tokens": i, "cache_creation_input_tokens": cc,
                              "cache_read_input_tokens": cr, "output_tokens": o},
                    "content": [{"type": "text", "text": "x"}]},
    })


def test_dedup_by_message_id():
    """Three JSONL entries sharing one message id count usage exactly once."""
    with tempfile.NamedTemporaryFile("w", suffix=".output", delete=False) as f:
        f.write(json.dumps({"type": "user", "timestamp": "2026-07-04T21:59:00.000Z",
                            "message": {"content": "spawn prompt"}}) + "\n")
        for _ in range(3):
            f.write(_entry("msg_dup") + "\n")
        f.write(_entry("msg_other", i=10, cc=20, cr=5, o=5) + "\n")
        path = Path(f.name)
    try:
        info = bw.parse_transcript(path)
        # msg_dup once (100+200+50=350) + msg_other (10+20+5=35)
        assert info["fresh_tokens"] == 385, info["fresh_tokens"]
        assert info["cache_read_tokens"] == 1005, info["cache_read_tokens"]
        assert info["assistant_msgs"] == 2, info["assistant_msgs"]
    finally:
        os.unlink(path)
    print("ok test_dedup_by_message_id")


def _make_watch_env(tmp, completed: bool):
    """Task transcript over a tiny cap + parent session with/without a
    completed task-notification. Returns (root, sessions_dir, state)."""
    sid = "11111111-2222-3333-4444-555555555555"
    tasks = tmp / "root" / sid / "tasks"
    tasks.mkdir(parents=True)
    out = tasks / "adeadbeef00000001.output"
    lines = [json.dumps({"type": "user", "timestamp": "2026-07-04T21:59:00.000Z",
                         "message": {"content": "Execute this nightwatch task: fake"}})]
    for n in range(5):
        lines.append(_entry(f"m{n}", i=100, cc=100, o=100))  # fresh=1500 total
    out.write_text("\n".join(lines) + "\n")

    sessions = tmp / "sessions"
    sessions.mkdir()
    notif = ("<task-notification>\n<task-id>adeadbeef00000001</task-id>\n"
             "<status>completed</status>\n"
             "<usage><subagent_tokens>4242</subagent_tokens></usage>\n"
             "</task-notification>")
    entries = []
    if completed:
        entries.append(json.dumps({
            "type": "attachment",
            "timestamp": "2099-01-01T00:00:00.000Z",  # after transcript mtime
            "attachment": {"type": "queued_command", "prompt": notif},
        }))
    (sessions / f"{sid}.jsonl").write_text("\n".join(entries) + "\n" if entries else "")
    return tmp / "root", sessions, tmp / "state.json"


def _run_watch(root, sessions, state, max_tokens=1000):
    return subprocess.run(
        [sys.executable, str(BW), "watch", "--root", str(root),
         "--sessions-dir", str(sessions), "--state", str(state),
         "--max-tokens", str(max_tokens), "--active-minutes", "999999"],
        capture_output=True, text=True)


def test_completed_task_never_alerts():
    with tempfile.TemporaryDirectory() as d:
        root, sessions, state = _make_watch_env(Path(d), completed=True)
        r = _run_watch(root, sessions, state)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "BUDGET ALERT" not in r.stdout, r.stdout
    print("ok test_completed_task_never_alerts")


def test_running_task_over_cap_alerts_once_when_static():
    with tempfile.TemporaryDirectory() as d:
        root, sessions, state = _make_watch_env(Path(d), completed=False)
        r1 = _run_watch(root, sessions, state)
        assert r1.returncode == 2 and "fresh tokens" in r1.stdout, r1.stdout
        # second run, transcript unchanged -> suppressed (no growth past alert)
        r2 = _run_watch(root, sessions, state)
        assert r2.returncode == 0, r2.stdout + r2.stderr
        # transcript grows past the alerted value -> fires again
        out = root / "11111111-2222-3333-4444-555555555555" / "tasks" / "adeadbeef00000001.output"
        with open(out, "a") as f:
            f.write(_entry("m_new", i=100, cc=100, o=100) + "\n")
        r3 = _run_watch(root, sessions, state)
        assert r3.returncode == 2, r3.stdout
    print("ok test_running_task_over_cap_alerts_once_when_static")


if __name__ == "__main__":
    test_dedup_by_message_id()
    test_completed_task_never_alerts()
    test_running_task_over_cap_alerts_once_when_static()
    print("all tests passed")
