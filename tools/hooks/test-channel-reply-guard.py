#!/usr/bin/env python3
"""Tests for channel-reply-guard.py. Pipes hook-style stdin JSON at the hook
and asserts allow (exit 0, no block decision) or block (exit 0 with
{"decision": "block"} on stdout).

Run: python3 tools/hooks/test-channel-reply-guard.py
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "channel-reply-guard.py")
FIXTURES = os.path.join(HERE, "fixtures")


def run_hook(transcript, stop_hook_active=False):
    payload = json.dumps(
        {
            "transcript_path": os.path.join(FIXTURES, transcript),
            "stop_hook_active": stop_hook_active,
            "hook_event_name": "Stop",
        }
    )
    proc = subprocess.run(
        ["python3", HOOK],
        input=payload,
        capture_output=True,
        text=True,
        timeout=15,
    )
    decision = None
    if proc.stdout.strip():
        try:
            decision = json.loads(proc.stdout).get("decision")
        except json.JSONDecodeError:
            pass
    return proc.returncode, decision


def main():
    cases = [
        # (name, transcript, stop_hook_active, expect_block)
        ("bluebubbles inbound + reply sent -> allow", "bluebubbles-replied.jsonl", False, False),
        ("bluebubbles inbound, no reply -> block", "bluebubbles-no-reply.jsonl", False, True),
        ("no channel message -> allow", "no-channel.jsonl", False, False),
        ("no reply but stop_hook_active -> allow (one block max)", "bluebubbles-no-reply.jsonl", True, False),
        ("missing transcript -> allow (fail open)", "does-not-exist.jsonl", False, False),
    ]
    failures = 0
    for name, transcript, active, expect_block in cases:
        rc, decision = run_hook(transcript, stop_hook_active=active)
        blocked = decision == "block"
        ok = rc == 0 and blocked == expect_block
        print(f"{'PASS' if ok else 'FAIL'}: {name} (rc={rc}, decision={decision})")
        if not ok:
            failures += 1
    if failures:
        print(f"{failures} test(s) failed")
        sys.exit(1)
    print("All tests passed")


if __name__ == "__main__":
    main()
