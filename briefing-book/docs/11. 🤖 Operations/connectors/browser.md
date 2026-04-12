---
type: connector-docs
connector: browser
---

# Browser Connector

Archives browsing history from Safari and Chrome into daily markdown files.

## Quick Setup

No configuration needed -- reads directly from macOS. Requires Full Disk Access for Safari history.

**Database locations:**
- Safari: `~/Library/Safari/History.db`
- Chrome: `~/Library/Application Support/Google/Chrome/Default/History`

Either or both browsers can be present -- missing ones are silently skipped.

## What It Captures

- Page URLs and titles from both Safari and Chrome
- Visit timestamps
- Visit counts (deduped per URL per day, with repeat counts noted)
- Browser attribution (Safari vs Chrome)

Filtered out: chrome:// URLs, OAuth flows, localhost, extension URLs, data: URIs, and URLs over 500 characters.

## How It Works

- Copies browser databases to temp files before reading (browsers lock their DBs)
- Safari timestamps: seconds since 2001-01-01 UTC
- Chrome timestamps: microseconds since 1601-01-01 UTC
- Merges both browsers into unified daily files, sorted by time
- Groups entries by hour within each day
- Deduplicates URLs within the same day (keeps first visit, notes repeat count)

## Output Format

```
~/Edwin/data/browser/
  history/
    2026-04/
      2026-04-10.md
      2026-04-11.md
```

Each daily file has hour-grouped sections with entries like:
`- [Page Title](url) (Safari, 2:15 PM) (x3)`

## Cadence

Every 2 hours via scheduler.
