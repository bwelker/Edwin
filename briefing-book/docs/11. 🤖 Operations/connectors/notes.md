---
type: connector-docs
connector: notes
---

# Notes Connector

Archives Apple Notes from the macOS NoteStore database.

## Quick Setup

No configuration needed -- reads directly from macOS. Requires Full Disk Access.

**Database location:**
```
~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite
```

## What It Captures

- Note title, folder, and full body text
- Creation and modification timestamps
- Note identifiers for dedup/update tracking

Notes containing credential-like patterns (API keys, passwords, AWS secrets, etc.) are automatically skipped for security.

## How It Works

- Reads NoteStore.sqlite in read-only mode
- Note bodies are stored as gzip-compressed protobuf blobs (ZDATA column)
- Decompresses and extracts the largest contiguous text block from the binary
- Falls back to the ZSNIPPET field if body extraction fails
- Writes one markdown file per note, organized by folder
- Incremental sync uses CoreData modification timestamps
- Deleted notes (ZMARKEDFORDELETION) are excluded

## Output Format

```
~/Edwin/data/notes/
  notes/
    {folder}/
      {sanitized-title}.md
```

Each note file has YAML frontmatter with source, folder, dates, and the full note body.

## Cadence

Every 2 hours via scheduler.
