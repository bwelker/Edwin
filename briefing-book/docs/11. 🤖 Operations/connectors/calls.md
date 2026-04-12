---
type: connector-docs
connector: calls
---

# Calls Connector

Archives phone call history from the macOS CallHistory database (synced from iPhone via iCloud).

## Quick Setup

No configuration needed -- reads directly from macOS. Requires Full Disk Access and iCloud call history sync enabled on iPhone.

**Database location:**
```
~/Library/Application Support/CallHistoryDB/CallHistory.storedata
```

## What It Captures

- All phone calls, FaceTime Audio, and FaceTime Video calls
- Call direction (incoming, outgoing, missed)
- Call duration
- Caller name and phone number
- Call type classification (Phone, FaceTime Audio, FaceTime Video)
- Identity resolution via the identity registry (phone number to name)

## How It Works

- Reads `CallHistory.storedata` (SQLite/CoreData) in read-only mode
- Converts CoreData timestamps (Unix epoch + 978307200 offset) to local time
- Joins ZCALLRECORD with ZHANDLE for normalized phone numbers
- Deduplicates call records by ZUNIQUE_ID
- Resolves caller names: DB name > identity registry > raw phone number
- Merges incrementally with existing daily files to avoid overwriting

## Output Format

```
~/Edwin/data/calls/
  2026-04/
    2026-04-10.md
    2026-04-11.md
```

Each daily file contains a call log with entries like:
`- **2:15 PM** -- John Smith (incoming, 5m 30s, Phone)`

## Cadence

Daily via scheduler (9 PM).
