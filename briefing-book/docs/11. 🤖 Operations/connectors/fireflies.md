---
type: connector-docs
connector: fireflies
---

# Fireflies Connector

Syncs meeting transcripts, audio, and video from Fireflies.ai.

## Quick Setup

Requires a Fireflies API key (Business plan or higher for full API access).

### 1. Get API Key

Log in to [Fireflies.ai](https://fireflies.ai/) > Settings > Developer > API Key.

### 2. Store Credentials

Create `~/.edwin/credentials/fireflies/env`:
```bash
FIREFLIES_API_KEY=your-api-key-here
```

Or set as an environment variable, or add to `~/Edwin/.env`.

### 3. Verify

```bash
./connectors/fireflies/fireflies status
```

## What It Captures

- **Transcripts**: Full meeting transcripts with speaker attribution, timestamps, duration, attendees, and AI-generated summaries
- **Audio** (on-demand): Meeting audio recordings
- **Video** (on-demand): Meeting video recordings

The `sync all` command syncs transcripts only. Audio and video are on-demand (`sync audio`, `sync video`).

## How It Works

- GraphQL API at `https://api.fireflies.ai/graphql`
- Bearer token authentication
- Rate limited to 60 requests/minute (1.05s minimum interval)
- Longer throttle cooldown (5s) -- Fireflies rate limits are stricter
- Fetches transcript list with pagination, then full transcript details per meeting
- Exponential backoff with Retry-After header support
- One markdown file per meeting transcript

## Output Format

```
~/Edwin/data/fireflies/
  transcripts/
    2026-04/
      2026-04-10-0930-weekly-standup.md
      2026-04-10-1400-product-review.md
  audio/                                # On-demand only
    2026-04/
      ...
  video/                                # On-demand only
    2026-04/
      ...
```

Each transcript file contains YAML frontmatter (title, date, duration, attendees, summary) and the full speaker-attributed transcript.

## Cadence

Daily via scheduler (9 PM).
