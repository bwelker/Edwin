---
type: connector-docs
connector: photos
---

# Photos Connector

Archives photo and video metadata from the Apple Photos library database. No actual images are stored -- only timestamps, filenames, and GPS coordinates.

## Quick Setup

No configuration needed -- reads directly from macOS. Requires Full Disk Access.

**Database location:**
```
~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite
```

## What It Captures

- Photo/video creation timestamps
- Filenames
- GPS coordinates with rough reverse geocoding (matches against known cities)
- Media type (photo vs video)
- Daily counts and location summaries

## How It Works

- Reads Photos.sqlite (ZASSET table) in read-only mode
- Converts CoreData timestamps to local time
- Groups photos/videos by day
- Performs rough reverse geocoding by matching GPS coordinates against a list of known city coordinates (within ~0.08 degrees / ~5 miles)
- Writes daily summary files with photo/video counts and locations
- Incremental sync tracks the max CoreData timestamp

## Output Format

```
~/Edwin/data/photos/
  metadata/
    2026-04/
      2026-04-10.md
      2026-04-11.md
```

Each daily file lists photo counts, video counts, and locations visited.

## Cadence

Daily via scheduler (9 PM).
