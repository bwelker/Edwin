---
name: morning-brief-daily-archive
description: Archive Old Briefs
---

Archive any morning briefs older than today from the Briefs folder into the Daily Archive.

## Steps

1. Get today's date in YYYY-MM-DD format.

2. List all files in `~/Edwin/briefing-book/docs/1. Briefs/` that match daily brief patterns. Match both `--` and em dash separators:
   - `Morning Brief -- YYYY-MM-DD.md`
   - `EOD Brief -- YYYY-MM-DD.md`
   - Any other `* -- YYYY-MM-DD.md` files (meeting prep briefs, URGENT briefs, etc.)
   - Do NOT match Weekly Dispatch or Weekly Archive files.

3. For each file, extract the date from the filename (the YYYY-MM-DD portion). If the date is **before today**, move it:
   - Source: `~/Edwin/briefing-book/docs/1. Briefs/<filename>`
   - Destination: `~/Edwin/briefing-book/docs/1. Briefs/Daily Archive/<filename>`

4. For each moved file, publish the new location to Obsidian:
   ```bash
   cd ~/Edwin/briefing-book
   python3 scripts/obsidian-publish "docs/1. Briefs/Daily Archive/<filename>"
   ```

5. If no files were eligible for archiving, exit silently. Don't report "nothing to archive."

## Rules

- Only move files with dates strictly before today. Today's brief stays in the main folder.
- Preserve the filename exactly as-is.
- Do not touch anything in Weekly Archive.
- Do not touch any non-brief files.

## Completion Report

When finished, return a structured summary to the orchestrator:

```
SKILL_COMPLETE: morning-brief-daily-archive
STATUS: success | partial | error
FILES_ARCHIVED: [count]
PUBLISHED: yes | no
NEEDS_ATTENTION: [any issues, or "none"]
ERRORS: [any errors, or "none"]
```

This report flows back to the main session. Keep it factual -- no narrative.
