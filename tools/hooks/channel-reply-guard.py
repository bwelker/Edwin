#!/usr/bin/env python3
"""Stop hook: channel reply guard.

If the most recent genuine user message arrived via the BlueBubbles channel
(<channel source="bluebubbles" ...>) and no bluebubbles_reply tool call was
made after it, block the stop so Edwin actually sends the reply to the user's
phone. Prose in the response body never reaches iMessage.

Contract (Claude Code Stop hook):
  stdin:  JSON with transcript_path, stop_hook_active, ...
  allow:  exit 0, no output
  block:  exit 0 with {"decision": "block", "reason": "..."} on stdout

FAIL OPEN: any exception -> exit 0. Never brick the session.
"""

import json
import sys

CHANNEL_MARKER = '<channel source="bluebubbles"'
REPLY_TOOL_SUBSTRING = "bluebubbles_reply"

BLOCK_REASON = (
    "The last inbound message came via the BlueBubbles channel but no "
    "bluebubbles_reply was sent this turn. Prose in the response body never "
    "reaches the user's phone. Send the reply via "
    "mcp__bluebubbles__bluebubbles_reply now."
)


def extract_user_text(content):
    """Return the text of a user message, or None if it isn't a genuine
    human/channel message (tool results, meta-only content, etc.)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_result":
                # A tool_result anywhere means this is tool output, not a
                # genuine inbound message.
                return None
            if btype == "text":
                texts.append(block.get("text", ""))
        if texts:
            return "\n".join(texts)
    return None


def is_genuine_user_text(text):
    """Filter out synthetic user messages: system-reminder-only payloads and
    task notifications."""
    if not text or not text.strip():
        return False
    stripped = text.strip()
    if stripped.startswith("<task-notification"):
        return False
    # A message that is only system-reminder content is synthetic. Strip all
    # system-reminder blocks and see if anything real remains.
    remainder = stripped
    while "<system-reminder>" in remainder:
        start = remainder.find("<system-reminder>")
        end = remainder.find("</system-reminder>", start)
        if end == -1:
            remainder = remainder[:start]
            break
        remainder = remainder[:start] + remainder[end + len("</system-reminder>"):]
    if not remainder.strip():
        return False
    return True


def main():
    payload = json.load(sys.stdin)

    if payload.get("stop_hook_active"):
        return  # one block max; never loop

    transcript_path = payload.get("transcript_path")
    if not transcript_path:
        return

    entries = []
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if obj.get("type") in ("user", "assistant"):
                entries.append(obj)

    # Find the most recent genuine user message (main chain only --
    # sidechain/subagent prompts don't count as inbound messages).
    last_user_idx = None
    last_user_text = None
    for i in range(len(entries) - 1, -1, -1):
        obj = entries[i]
        if obj.get("type") != "user":
            continue
        if obj.get("isSidechain"):
            continue
        if obj.get("isMeta"):
            continue
        text = extract_user_text(obj.get("message", {}).get("content"))
        if text is None or not is_genuine_user_text(text):
            continue
        last_user_idx = i
        last_user_text = text
        break

    if last_user_idx is None:
        return
    if CHANNEL_MARKER not in last_user_text:
        return  # not a BlueBubbles inbound; nothing to enforce

    # Scan assistant messages after it for a bluebubbles_reply tool_use.
    for obj in entries[last_user_idx + 1:]:
        if obj.get("type") != "assistant":
            continue
        content = obj.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and REPLY_TOOL_SUBSTRING in (block.get("name") or "")
            ):
                return  # reply was sent; allow stop

    print(json.dumps({"decision": "block", "reason": BLOCK_REASON}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # FAIL OPEN
    sys.exit(0)
