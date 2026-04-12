---
type: connector-docs
connector: plaud
---

# Plaud Connector

Syncs voice recordings and transcripts from the Plaud Note Pro device.

## Quick Setup

Requires a Plaud API token.

### 1. Get API Token

Extract the bearer token from the Plaud web interface or mobile app (check network requests for the authorization header).

### 2. Store Credentials

Create `~/.edwin/credentials/plaud/env`:
```bash
PLAUD_TOKEN=your-bearer-token-here
PLAUD_API_DOMAIN=https://api.plaud.ai
```

The `PLAUD_API_DOMAIN` defaults to `https://api.plaud.ai` if not set.

### 3. Test Connection

```bash
./connectors/plaud/plaud --test
```

### 4. List Recordings

```bash
./connectors/plaud/plaud --list
```

## What It Captures

- Recording metadata (name, duration, timestamp, speakers)
- AI-generated summaries (from Plaud's pre-processing)
- Full speaker-attributed transcripts with timestamps
- Transcript segments fetched from S3 presigned URLs (may be gzip-compressed JSON)

## How It Works

- REST API with bearer token authentication
- Lists recordings via `/file/simple/web` endpoint
- Fetches full details per recording via `/file/detail/{id}`
- Transcripts are stored as JSON on S3 -- fetched via presigned URLs in the content_list
- AI summaries extracted from `pre_download_content_list` (auto_sum entries)
- State tracking prevents re-processing of already-synced recordings
- Supports `--all` flag to force re-sync everything

## Output Format

```
~/Edwin/data/plaud/
  recordings/
    2026-04/
      2026-04-10-meeting-notes.md
```

Each recording file contains: title, date, duration, speaker list, AI summary, and the full transcript with speaker attribution and timestamps.

## Cadence

Daily via scheduler.
