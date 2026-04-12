---
name: weekly-archive
description: Archive Old Weekly Dispatches
---

Archive any weekly dispatches older than the current week from the Briefs folder into the Weekly Archive.

## Steps

1. Get today's date and determine the current ISO week number (YYYY-WNN format).

2. List all files in `~/Edwin/briefing-book/docs/1. Briefs/` that match the pattern `Weekly Dispatch*`.

3. For each file, extract the week identifier from the filename (e.g., "2026-W13"). If the week is **before the current week**, move it:
   - Source: `~/Edwin/briefing-book/docs/1. Briefs/<filename>`
   - Destination: `~/Edwin/briefing-book/docs/1. Briefs/Weekly Archive/<filename>`

4. For each moved file, publish the new location to Obsidian:
   ```bash
   cd ~/Edwin/briefing-book
   python3 scripts/obsidian-publish "docs/1. Briefs/Weekly Archive/<filename>"
   ```

5. If no files were eligible for archiving, exit silently. Don't report "nothing to archive."

## Rules

- Only move dispatches from weeks strictly before the current week. Current week's dispatch stays in the main folder.
- Preserve the filename exactly as-is.
- Do not touch anything in Daily Archive.
- Do not touch non-dispatch files (Morning Briefs, EOD Briefs, etc.).

## Completion Report

When finished, return a structured summary to the orchestrator:

```
SKILL_COMPLETE: weekly-archive
STATUS: success | partial | error
FILES_ARCHIVED: [count]
PUBLISHED: yes | no
NEEDS_ATTENTION: [any issues, or "none"]
ERRORS: [any errors, or "none"]
```

This report flows back to the main session. Keep it factual -- no narrative.
