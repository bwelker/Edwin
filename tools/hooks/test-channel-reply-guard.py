#!/usr/bin/env python3
"""Regression tests for channel-reply-guard.py (Stop hook).

Each test writes a temp JSONL transcript modeling a real Claude Code turn
structure, pipes a Stop-hook payload at the hook, and asserts allow (exit 0,
no decision) or block (exit 0 with {"decision": "block"}).

The transcript entries mirror what the *live* session actually records --
crucially, genuine channel inbound messages carry isMeta==true and
origin.kind=="channel" (this is the exact shape that broke the guard once),
and injected UserPromptSubmit context arrives as type=="attachment" entries,
not user entries.

Run: python3 tools/hooks/test-channel-reply-guard.py
"""

import json
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "channel-reply-guard.py")

CHANNEL_CONTENT = (
    '<channel source="bluebubbles" sender="+15551234567" sender_name="Alice" '
    'chat_guid="iMessage;-;+15551234567" message_guid="ABC-123" '
    'has_attachments="false">\nSo everything is done?\n</channel>'
)


def channel_msg(content=CHANNEL_CONTENT):
    """A genuine channel inbound: user entry, isMeta true, origin channel."""
    return {
        "type": "user",
        "isSidechain": False,
        "isMeta": True,
        "promptSource": "system",
        "origin": {"kind": "channel", "server": "bluebubbles"},
        "message": {"role": "user", "content": content},
    }


def typed_msg(text):
    """A genuine typed-at-CLI inbound: origin.kind human, not meta."""
    return {
        "type": "user",
        "isSidechain": False,
        "promptSource": "typed",
        "origin": {"kind": "human"},
        "message": {"role": "user", "content": text},
    }


def injected_context_attachment():
    """UserPromptSubmit hook injection -- arrives as type==attachment, NOT user.

    The guard collects only type in (user, assistant), so this must be ignored.
    """
    return {
        "type": "attachment",
        "isSidechain": False,
        "attachment": {
            "type": "hook_additional_context",
            "content": ["<relevant-memories>\nsome recalled memory\n</relevant-memories>"],
        },
    }


def assistant_text(text):
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def assistant_thinking():
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "..."}]},
    }


def assistant_tool_use(name, tid="toolu_1"):
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": tid, "name": name, "input": {}}],
        },
    }


def tool_result(tid="toolu_1", content="ok"):
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tid, "content": content}],
        },
    }


def sidechain_channel_prompt():
    """A subagent/sidechain prompt that quotes the channel marker -- must NOT
    count as an inbound message."""
    e = channel_msg()
    e["isSidechain"] = True
    return e


def task_notification():
    return {
        "type": "user",
        "isSidechain": False,
        "message": {
            "role": "user",
            "content": "<task-notification>Agent xyz completed.</task-notification>",
        },
    }


def run_hook(entries, stop_hook_active=False):
    """Write entries to a temp transcript, invoke the hook, return (rc, decision)."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
    ) as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
        path = f.name
    try:
        payload = json.dumps(
            {
                "transcript_path": path,
                "stop_hook_active": stop_hook_active,
                "hook_event_name": "Stop",
            }
        )
        proc = subprocess.run(
            ["python3", HOOK], input=payload, capture_output=True, text=True, timeout=15
        )
        decision = None
        if proc.stdout.strip():
            try:
                decision = json.loads(proc.stdout).get("decision")
            except json.JSONDecodeError:
                pass
        return proc.returncode, decision
    finally:
        os.unlink(path)


class ChannelReplyGuardTest(unittest.TestCase):
    def assertBlocks(self, entries, **kw):
        rc, decision = run_hook(entries, **kw)
        self.assertEqual(rc, 0, "hook must always exit 0 (fail-open)")
        self.assertEqual(decision, "block", "expected a block decision")

    def assertAllows(self, entries, **kw):
        rc, decision = run_hook(entries, **kw)
        self.assertEqual(rc, 0, "hook must always exit 0 (fail-open)")
        self.assertIsNone(decision, "expected no block decision")

    # --- the regression: channel inbound (isMeta true) + injected context +
    #     assistant plain-text-only reply -> MUST BLOCK ---
    def test_channel_inbound_plain_text_reply_blocks(self):
        self.assertBlocks(
            [
                channel_msg(),
                injected_context_attachment(),
                assistant_thinking(),
                assistant_text("Yes -- everything you greenlit tonight is shipped."),
            ]
        )

    def test_channel_inbound_no_assistant_at_all_blocks(self):
        self.assertBlocks([channel_msg(), injected_context_attachment()])

    # --- passing case: reply actually sent -> ALLOW ---
    def test_channel_inbound_reply_sent_allows(self):
        self.assertAllows(
            [
                channel_msg(),
                injected_context_attachment(),
                assistant_text("On it."),
                assistant_tool_use("mcp__bluebubbles__bluebubbles_reply", "toolu_2"),
                tool_result("toolu_2", "Message sent"),
                assistant_text("Reply sent to Alice."),
            ]
        )

    # --- must-not-block cases ---
    def test_non_channel_typed_inbound_allows(self):
        self.assertAllows(
            [typed_msg("clean up the scratch files"), assistant_text("Done.")]
        )

    def test_sidechain_channel_prompt_does_not_block(self):
        # A subagent prompt that quotes the channel marker is not an inbound.
        self.assertAllows(
            [sidechain_channel_prompt(), assistant_text("subagent working")]
        )

    def test_task_notification_does_not_block(self):
        self.assertAllows([task_notification(), assistant_text("noted")])

    def test_stop_hook_active_short_circuits(self):
        # One block max: if we already blocked once this turn, allow the stop.
        self.assertAllows(
            [channel_msg(), assistant_text("plain text only")],
            stop_hook_active=True,
        )

    def test_missing_transcript_fails_open(self):
        payload = json.dumps(
            {"transcript_path": "/does/not/exist.jsonl", "stop_hook_active": False}
        )
        proc = subprocess.run(
            ["python3", HOOK], input=payload, capture_output=True, text=True, timeout=15
        )
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")

    def test_later_typed_message_supersedes_channel(self):
        # Channel msg was answered; a later typed msg with no marker is the last
        # inbound -> no channel enforcement, allow.
        self.assertAllows(
            [
                channel_msg(),
                assistant_tool_use("mcp__bluebubbles__bluebubbles_reply", "toolu_2"),
                tool_result("toolu_2", "Message sent"),
                typed_msg("thanks"),
                assistant_text("anytime"),
            ]
        )

    def test_channel_then_channel_only_last_enforced(self):
        # Two channel inbounds; the last one is unanswered -> block.
        second = channel_msg(
            '<channel source="bluebubbles" sender="+15551234567" '
            'sender_name="Alice" chat_guid="iMessage;-;+15551234567" '
            'message_guid="DEF-456" has_attachments="false">\nHello?\n</channel>'
        )
        self.assertBlocks(
            [
                channel_msg(),
                assistant_tool_use("mcp__bluebubbles__bluebubbles_reply", "toolu_2"),
                tool_result("toolu_2", "Message sent"),
                second,
                assistant_text("plain text only, never sent"),
            ]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
