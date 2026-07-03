#!/usr/bin/env python3
"""PreCompact hook: memory flush welded to compaction.

Before Claude Code compacts a session, queue a memory-flush entry and spawn a
DETACHED headless summarizer (claude -p) that writes a session summary to
$EDWIN_HOME/memory/sessions/ following the CLAUDE.md template. The hook itself
does no LLM work and must return in well under a second.

Contract (Claude Code PreCompact hook):
  stdin: JSON with transcript_path, trigger ("manual"|"auto"), cwd, ...
  Always exit 0. FAIL OPEN on any error.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

EDWIN_HOME = os.environ.get("EDWIN_HOME", os.path.expanduser("~/Edwin"))
FLUSH_DIR = os.path.join(EDWIN_HOME, "data", "memory-flush")
PENDING_FILE = os.path.join(FLUSH_DIR, "pending.jsonl")
PRUNE_DAYS = 7


def prune_queue():
    """Drop queue entries older than PRUNE_DAYS."""
    if not os.path.exists(PENDING_FILE):
        return
    cutoff = datetime.now() - timedelta(days=PRUNE_DAYS)
    kept = []
    with open(PENDING_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
                ts = datetime.fromisoformat(obj.get("timestamp", ""))
                if ts >= cutoff:
                    kept.append(line)
            except (ValueError, TypeError, KeyError):
                # Unparseable line: keep it rather than silently destroy data.
                kept.append(line)
    tmp = PENDING_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for line in kept:
            f.write(line + "\n")
    os.replace(tmp, PENDING_FILE)


def build_prompt(transcript_path, entry_id):
    return (
        "You are Edwin's headless session summarizer, fired by a PreCompact "
        "hook. Do the following:\n"
        f"1. Read the session transcript JSONL at {transcript_path} "
        "(each line is a JSON object; type 'user' and 'assistant' entries "
        "hold the conversation).\n"
        "2. Produce a session summary following the exact template in "
        f"{EDWIN_HOME}/CLAUDE.md (Session Summarizer section): frontmatter with "
        "date and type session-summary, then sections Gist / Decisions / "
        "Tension Map / Commitments / User State / Key Identifiers / "
        "Blocked Items / Next. Preserve identifiers verbatim. Don't "
        "editorialize. Over-capture beats under-capture.\n"
        f"3. Write it to {EDWIN_HOME}/memory/sessions/YYYY-MM-DD-HHMM-summary.md "
        "using the current date and time.\n"
        "4. Mark this queue entry done by appending a single JSON line to "
        f"{PENDING_FILE} of the form "
        f'{{"done": "{entry_id}", "summary_path": "<path you wrote>", '
        '"timestamp": "<now, ISO 8601>"}.\n'
        "Do not do anything else."
    )


def main():
    payload = json.load(sys.stdin)
    transcript_path = payload.get("transcript_path", "")
    trigger = payload.get("trigger", "unknown")
    cwd = payload.get("cwd") or os.getcwd()

    os.makedirs(FLUSH_DIR, exist_ok=True)

    now = datetime.now()
    entry_id = now.strftime("%Y%m%d-%H%M%S-") + str(os.getpid())
    entry = {
        "id": entry_id,
        "timestamp": now.isoformat(),
        "transcript_path": transcript_path,
        "trigger": trigger,
        "cwd": cwd,
    }
    with open(PENDING_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

    try:
        prune_queue()
    except Exception:
        pass  # pruning is housekeeping; never let it break the flush

    claude_bin = shutil.which("claude")
    if not claude_bin:
        return  # queued; a later pass can drain the queue

    log_file = os.path.join(FLUSH_DIR, f"summarizer-{entry_id}.log")
    with open(log_file, "ab") as log:
        subprocess.Popen(
            [
                claude_bin,
                "-p",
                build_prompt(transcript_path, entry_id),
                "--model",
                "claude-sonnet-5",
                # Budget cap: read transcript -> write summary -> append queue
                # line is ~10-15 turns; 25 leaves headroom while making a
                # runaway summarizer mechanically impossible.
                "--max-turns",
                "25",
            ],
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=EDWIN_HOME,
        )
    # Do NOT wait. The detached process does the slow work.


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # FAIL OPEN
    sys.exit(0)
