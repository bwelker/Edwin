---
type: connector-docs
connector: google
---

# Google Connector

Syncs Gmail and Google Calendar via the Google APIs.

## Quick Setup

Requires a Google OAuth 2.0 client credential.

### 1. Create OAuth Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/) > APIs & Services > Credentials
2. Create an OAuth 2.0 Client ID (Desktop application type)
3. Download the client secret JSON

### 2. Install Credentials

Place the OAuth client JSON at:
```
~/Library/Application Support/gogcli/credentials.json
```

The file needs `client_id` and `client_secret` fields at the top level.

### 3. Authenticate

```bash
./connectors/google/google auth
```

This opens a browser for Google OAuth consent. Token is saved to `~/.config/edwin/google-token.json` with auto-refresh.

**Scopes requested:**
- `gmail.readonly` -- read email (no modify)
- `calendar` -- read/write calendar
- `userinfo.email` -- identify the account

### 4. Verify

```bash
./connectors/google/google status
```

## What It Captures

- **Gmail**: Full email messages (subject, from, to, date, body, read status) -- one file per email
- **Calendar**: Events from all calendars (title, time, location, attendees, description, Meet links, recurring event detection)

## How It Works

- **Gmail backfill**: Month-by-month date-range search to avoid deep pagination timeouts
- **Gmail incremental**: History API with messageAdded events; falls back to 7-day backfill if history ID expires
- **Gmail batch**: Fetches up to 100 messages per batch request; failed messages retry individually
- **Calendar backfill**: Full sync with date range, recurring events capped at 90 days out
- **Calendar incremental**: syncToken-based; falls back to full sync on 410 (token expired)
- Token auto-refresh via google-auth-httplib2 on 401 responses
- Atomic file writes (temp + os.replace) to prevent corruption

## Output Format

```
~/Edwin/data/google/
  mail/
    2026-04/
      2026-04-10-143022-a1b2c3d4.md    # One file per email
  calendar/
    2026-04/
      2026-04-10.md                     # Day-grouped events
```

## Cadence

- Mail: every 30 minutes
- Calendar: every 120 minutes
