---
type: connector-docs
connector: sessions
---

# Sessions Connector

Archives Claude Code session logs (JSONL) into readable markdown, one file per session.

## Quick Setup

No configuration needed -- reads directly from the local filesystem.

**Source directory:**
```
~/.claude/projects/
```

All `*.jsonl` files under any project subdirectory are processed.

## What It Captures

- User messages and assistant responses from Claude Code sessions
- Tool usage summaries (Read, Write, Edit, Bash, Grep, Glob, Agent, etc.)
- Session metadata: model, project, date range, tools used
- Conversation flow with timestamps

Thinking blocks are skipped. Tool results are skipped (they appear as user-type messages). Sessions with fewer than 3 real turns are ignored. Sessions containing credential-like patterns are automatically skipped.

## How It Works

- Scans `~/.claude/projects/` for JSONL files
- Each line in a JSONL file is a JSON object with types: user, assistant, queue-operation, progress
- Extracts user messages and assistant text/tool_use blocks
- Formats tool usage as brief blockquote summaries (e.g., `> Used tool: Read (~/.claude/settings.json)`)
- Deduplicates by session ID -- only processes new or modified sessions
- Default backfill: 90 days

## Output Format

```
~/Edwin/data/sessions/
  claude-code/
    {session-id}.md
```

Each session file contains YAML frontmatter (source, session ID, model, project, date range, tools used) followed by the conversation formatted as user/assistant turns.

## Cadence

Every 2 hours via scheduler.
