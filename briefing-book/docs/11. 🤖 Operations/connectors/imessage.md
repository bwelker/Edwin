---
type: connector-docs
connector: imessage
---

# iMessage Connector

Archives iMessage and SMS conversations from the macOS Messages database.

## Quick Setup

No configuration needed -- reads directly from macOS. Requires Full Disk Access for the process running the connector.

**Verify access:**
```bash
ls ~/Library/Messages/chat.db
```

If that fails, grant Full Disk Access in System Settings > Privacy & Security.

## What It Captures

- All iMessage and SMS conversations (incoming and outgoing)
- Message text, timestamps, sender handles
- Voice message transcriptions (extracted from NSAttributedString binary plists)
- Attachment metadata (filename, MIME type, size) -- not the actual files
- Group chat participants and display names
- Sender identity resolution via the identity registry (phone/email to name)

## How It Works

- Reads `~/Library/Messages/chat.db` in read-only mode via SQLite
- Converts Apple nanosecond timestamps (epoch 2001-01-01) to local time
- Groups messages by conversation (chat ROWID), then by day
- Deduplicates using SHA1 id-hashes of message GUIDs
- Writes both legacy conversation files (full history per contact) and per-day files for embedder chunking
- Incremental sync tracks the max Apple timestamp from the last run

## Output Format

```
~/Edwin/data/imessage/
  conversations/           # Full conversation history per contact
    +15551234567.md
    group-33.md
    John-Smith.md
  daily/                   # Per-day files for embedder indexing
    +15551234567/
      2026-04-10.md
      2026-04-11.md
```

Each message is formatted as: `**Sender** (time): message text`
with hidden `<!-- idhash: ... -->` comments for dedup tracking.

## Cadence

Every 60-120 minutes via scheduler.
