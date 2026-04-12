---
name: weekly-dispatch
description: Generate the Weekly Dispatch -- a full week retrospective covering wins, commitments, open items, team signals, decisions, red flags, and next week preview.
---

# Weekly Dispatch

Generate the Weekly Dispatch -- a comprehensive week-in-review that covers what happened, what's stuck, and what's coming. Published to the Briefing Book every Friday by 8 PM.

## Data Gathering

Collect data from all available sources for the current week (Monday through today). Run these in parallel where possible.

### 1. Session summaries
Read all `memory/sessions/*-summary.md` files from this week. These contain decisions, commitments, tension maps, and user state observations.

### 2. PM items
- `pm_list` filter "open" -- all open items, check which are overdue
- `pm_list` filter "done" -- items completed this week (look at completed_at dates)
- Count: total open, total overdue, completed this week, due this week

### 3. Calendar
Read `data/o365/calendar/YYYY-MM/` and `data/google/calendar/YYYY-MM/` for this week and next week. Count meetings per day.

### 4. Email signals
Search recent email for threads involving leadership or VIPs that indicate strategic shifts, budget discussions, org changes, or escalations. Use `memory_search` with date filters.

### 5. Teams signals
Search `data/o365/teams/` for this week's messages. Look for patterns: who's communicating what, escalations, blockers.

### 6. Fireflies transcripts
Read `data/fireflies/transcripts/YYYY-MM/` for this week. Identify key meetings and extract decisions/commitments.

### 7. Limitless lifelogs
Search `data/limitless/lifelogs/YYYY-MM/` for this week. Look for off-calendar conversations, impromptu decisions, emotional signals.

### 8. iMessage
Search `data/imessage/daily/` for this week. Look for personal context items (family, health, mood).

### 9. Infrastructure metrics
- Qdrant point count
- Neo4j entity count
- Plombery pipeline health
- Any connector failures this week

## Synthesis

Organize findings into these sections. Be specific. Use names, dates, numbers. No vague language.

### Wins
What went right this week. Ship dates hit, deals closed, hires made, blockers cleared, processes improved. Be generous but honest -- if something was a win, say so. If it was mediocre, don't list it.

### Commitments Scorecard
Two tables:
1. **Your commitments** -- what you owe others, status (on track / slipping / overdue / done)
2. **Others' commitments to you** -- what people owe you, status

Pull from PM items. Cross-reference with session summaries and meeting transcripts for status updates.

### Still Open
Items that were open at the start of the week and still are. Focus on the ones that matter -- stale blockers, delayed decisions, aging promises.

### Team Signals
What's happening with the people. Read between the lines of meetings, emails, and messages. Who's stepping up, who's struggling, what dynamics are shifting. Be observant but not gossipy. The user uses this to calibrate 1:1s and interventions.

### Key Decisions This Week
Decisions made or forced this week. What was decided, by whom, and what it means. Include decisions the user made and decisions that were made around them.

### Red Flags
Things that could blow up if ignored. Be direct. These are the items where the observation-not-instruction principle matters most -- make the implication visible, let the user decide what to do.

### Next Week Preview
Calendar overview for next week. Key meetings, deadlines, travel. What prep is needed. What's likely to be contentious.

### By the Numbers
Quick metrics table: PM open/overdue/completed, meetings this week, Qdrant vectors, key hires pending, days since [relevant milestone].

## Output

Write to: `~/Edwin/briefing-book/docs/1. Briefs/Weekly Dispatch -- YYYY-WNN.md`

Where WNN is the ISO week number.

Format: Follow the existing Weekly Dispatch format exactly (see prior dispatches in the Briefs folder). Use the same section headers.

After writing, publish to Obsidian:
```
python3 briefing-book/scripts/obsidian-publish --all
```

## Completion Report

```
SKILL_COMPLETE: weekly-dispatch
STATUS: success | error
ARTIFACT: ~/Edwin/briefing-book/docs/1. Briefs/Weekly Dispatch -- YYYY-WNN.md
WEEK: YYYY-WNN
WINS: [count]
RED_FLAGS: [count]
PM_COMPLETED: [count this week]
PM_OVERDUE: [count]
ERRORS: [any errors, or "none"]
```
