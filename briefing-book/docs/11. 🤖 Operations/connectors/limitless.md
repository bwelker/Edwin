---
type: connector-docs
connector: limitless
---

# Limitless Connector

Syncs lifelogs, Ask AI chats, and audio recordings from the Limitless AI pendant.

## Quick Setup

Requires a Limitless API key.

### 1. Get API Key

Log in to [Limitless](https://www.limitless.ai/) and generate an API key from your account settings.

### 2. Store Credentials

Create `~/.edwin/credentials/limitless/env`:
```bash
LIMITLESS_API_KEY=your-api-key-here
```

Or set as an environment variable, or add to `~/Edwin/.env`.

### 3. Verify

```bash
./connectors/limitless/limitless status
```

## What It Captures

- **Lifelogs**: Conversations captured by the Limitless pendant -- title, timestamps, duration, AI-generated summaries, and full speaker-attributed transcripts
- **Chats**: Ask AI conversations (question/answer pairs)
- **Audio** (on-demand only): Raw audio recordings in OGG format, split into 2-hour chunks for long recordings

The `sync all` command syncs lifelogs + chats. Audio is on-demand only (`sync audio`).

## How It Works

- REST API with X-Api-Key header authentication
- Rate limited to 180 requests/minute (0.34s minimum interval between requests)
- Lifelogs fetched in daily windows with cursor pagination
- Chats fetched in descending order with early-stop when reaching previously synced date
- Handles Retry-After headers and body retryAfter fields on 429 responses
- Per-conversation files are the primary output (one file per lifelog)
- Atomic file writes throughout

## Output Format

```
~/Edwin/data/limitless/
  lifelogs/
    2026-04/
      2026-04-10-0930-meeting-with-pete.md
      2026-04-10-1400-standup.md
  chats/
    2026-04/
      2026-04-10.md                     # Day-grouped chats
  audio/                                # On-demand only
    2026-04/
      2026-04-10-meeting-with-pete.ogg
```

Each lifelog file contains YAML frontmatter, an AI summary, and a full speaker-attributed transcript.

## Cadence

Every 1 hour via scheduler.
