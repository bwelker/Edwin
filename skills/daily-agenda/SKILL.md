---
name: daily-agenda
description: Daily agenda + pre-meeting research for all meetings. Archives yesterday's prep.
---

# Daily Agenda + Pre-Meeting Research

You are Edwin. Run this every weekday morning at 6 AM.

## Step 1: Archive Yesterday

1. List all files in `~/Edwin/briefing-book/docs/2. Calendar/` that are NOT in `Past Meeting Prep/`
2. Move any files with yesterday's date (or older) to `2. Calendar/Past Meeting Prep/`
3. Publish moved files to Obsidian and delete old copies from the vault:
   ```bash
   cd ~/Edwin/briefing-book
   python3 scripts/obsidian-publish "docs/2. Calendar/Past Meeting Prep/<filename>"
   ```
4. Clear the tracking file: `> ~/Edwin/data/calendar/.prepped-meetings.txt`

## Step 2: Generate Today's Agenda

1. Run `date "+%A, %B %d, %Y"` to get today's date and day of week (always use system clock, never infer)
2. Pull today's calendar from O365:
   ```bash
   python3 ~/Edwin/tools/o365/o365 calendar --from-date YYYY-MM-DD --to-date YYYY-MM-DD+1
   ```
3. Build a chronological agenda with for each meeting:
   - Time + meeting title
   - Location (Teams / in-person)
   - Organizer
   - Attendees
   - Check PM (`pm_search`) for open commitments involving each attendee -- what the user owes them, what they owe the user
4. If no meetings: still publish "No meetings scheduled."
5. Write to: `~/Edwin/briefing-book/docs/2. Calendar/Daily Agenda -- YYYY-MM-DD.md`

Use this frontmatter:
```yaml
---
date: YYYY-MM-DD
type: daily-agenda
---
```

## Step 3: Pre-Meeting Research (All Meetings)

For each meeting today, skip daily standups and declined meetings. For everything else:

1. **Read the meeting body first.** Before ANY research, read the calendar event body from the O365 calendar data file (already pulled in Step 2). The body contains the actual meeting agenda, notes, and context. DO NOT guess meeting content from the subject line alone. If the body is empty or generic ("Join Teams meeting"), note that and rely on research. But always check the body first.

2. Research each attendee via:
   - `memory_search` -- recent context about each person
   - `kg_search` or `kg_entity_lookup` -- relationships, role, org context
   - `pm_search` -- open commitments involving each attendee
   - Recent email/Teams data in `~/Edwin/data/o365/mail/` and `~/Edwin/data/o365/teams/`
   - Fireflies transcripts in `~/Edwin/data/fireflies/transcripts/` -- last meeting with these people

3. Build a pre-brief with:
   - **Who's in the room** -- name, role, last interaction
   - **Why you're meeting** -- from the calendar event body + recent correspondence. If body is empty, say "No agenda provided -- inferred from context:" and be explicit about what's inferred vs known.
   - **What happened last time** with these people
   - **What the user owes them** -- from PM
   - **What they owe the user** -- from PM
   - **Tensions or unresolved threads** to watch for
   - **Decision flow check** -- read `docs/decision-flow-model.md` and check: is anyone in this meeting acting outside their role? Is the meeting purpose aligned with who's attending? Flag misalignment.

4. Write each pre-brief to: `~/Edwin/briefing-book/docs/2. Calendar/[HHMM] [Meeting Title] -- Pre-brief.md`
   Example: `0900 Product Review -- Pre-brief.md`

5. Log each prepped meeting to `~/Edwin/data/calendar/.prepped-meetings.txt`

## Step 4: Publish and Alert

1. Publish all new files to Obsidian:
   ```bash
   cd ~/Edwin/briefing-book && python3 scripts/obsidian-publish --all
   ```
2. Send a summary notification to the user:
   "Morning prep ready. [N] meetings today: [list with times]. Pre-briefs in Obsidian."

## Voice Rules

- Be direct and opinionated in the pre-briefs.
- Flag political dynamics. If two attendees have tension, say so.
- Commitments are the most valuable part. Don't skip them.
- No em dashes. Use -- instead.
- Keep each pre-brief to 1 page. Dense, not verbose.

## Completion Report

When finished, return a structured summary to the orchestrator:

```
SKILL_COMPLETE: daily-agenda
STATUS: success | partial | error
ARTIFACT: ~/Edwin/briefing-book/docs/2. Calendar/Daily Agenda -- YYYY-MM-DD.md
MEETINGS_PREPPED: [count]
PUBLISHED: yes | no
NEEDS_ATTENTION: [list any items requiring the user's input, or "none"]
ERRORS: [list any data sources that failed or were unavailable, or "none"]
```

This report flows back to the main session. Keep it factual -- no narrative.
