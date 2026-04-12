---
type: connector-docs
connector: screentime
---

# Screentime Connector

Archives app usage data from the macOS KnowledgeC database into daily screen time reports.

## Quick Setup

No configuration needed -- reads directly from macOS. Requires Full Disk Access.

**Database location:**
```
~/Library/Application Support/Knowledge/knowledgeC.db
```

## What It Captures

- App usage durations (which apps were in focus and for how long)
- Daily totals and per-app breakdowns
- Top app identification per day
- Friendly app name mapping (e.g., `com.microsoft.teams2` becomes "Teams")

Covers 80+ known app bundle IDs with friendly names, including Safari, Chrome, Teams, Outlook, VS Code, Slack, Claude Desktop, and more.

## How It Works

- Reads the `/app/usage` stream from KnowledgeC SQLite database in read-only mode
- Converts CoreData timestamps (Unix epoch + 978307200 offset) to local time
- Groups usage entries by day and aggregates duration per app
- Sorts apps by duration descending
- Filters out entries with less than 5 seconds of usage
- Overwrites daily files completely on each sync (full day recalculation)

## Output Format

```
~/Edwin/data/screentime/
  usage/
    2026-04/
      2026-04-10.md
      2026-04-11.md
```

Each daily file contains a markdown table:

```
| App | Duration |
|-----|----------|
| Teams | 3h 45m |
| VS Code | 2h 10m |
| Safari | 1h 30m |
```

## Cadence

Daily via scheduler (9 PM).
