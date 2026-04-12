---
name: limitless-analysis
description: Deep review of the day's Limitless recordings -- catch things meetings missed, extract insights, and prep tomorrow's context.
---

# Limitless Overnight Analysis

Deep analysis of today's Limitless lifelog recordings. The user wears a Limitless AI pendant that captures all conversations throughout the day -- both scheduled meetings and impromptu conversations. This skill reviews everything that was captured and surfaces what matters.

## Why This Exists

Meetings captured by Fireflies have structured transcripts. But a lot of important information flows through conversations that aren't formal meetings -- phone calls, hallway chats, thinking-out-loud moments. Limitless captures all of it. This skill reviews the full day and extracts what Edwin needs to know.

## Data Gathering

### 1. Read today's Limitless lifelogs
Read all files matching: `data/limitless/lifelogs/YYYY-MM/YYYY-MM-DD-*.md`

Each file is a conversation segment with:
- Time range and duration
- Summary
- Speaker-attributed transcript

### 2. Cross-reference with calendar
Read today's calendar (`data/o365/calendar/YYYY-MM/YYYY-MM-DD.md` and `data/google/calendar/YYYY-MM/YYYY-MM-DD.md`).

For each Limitless segment, determine:
- Was this a scheduled meeting? (match by time overlap with calendar events)
- Was this an off-calendar conversation? (no matching event = valuable ambient capture)
- Was this a phone call? (check `data/calls/` for matching timeframe)

### 3. Read today's Fireflies transcripts
Read `data/fireflies/transcripts/YYYY-MM/YYYY-MM-DD-*.md`.

Identify which Limitless segments are already covered by Fireflies (better quality transcripts). Focus Limitless analysis on segments NOT covered by Fireflies.

## Analysis

For each Limitless segment that isn't already covered by Fireflies:

### Conversation Classification
- **Work meeting** (captured by Limitless but not Fireflies)
- **Phone call** (personal or work)
- **Ambient/hallway conversation**
- **Solo thinking** (talking to oneself or dictating)
- **Family conversation** (keep private -- extract only logistics that affect schedule)
- **Other**

### Content Extraction
For each non-Fireflies segment:

1. **Key points** -- what was discussed, any decisions made
2. **Commitments** -- anything that should be a PM item (flag for pm-capture to pick up, or add directly)
3. **Emotional signals** -- the user's energy level, frustration points, excitement about something
4. **People mentioned** -- anyone referenced who might need follow-up
5. **Context for tomorrow** -- anything that should inform tomorrow's morning brief

### Pattern Analysis
Across all segments:

1. **Time allocation** -- how many hours in meetings vs. unstructured time vs. heads-down work?
2. **Who did the user talk to most today?** Cross-reference with org chart / priority relationships.
3. **Energy arc** -- how did energy/mood change through the day? (early morning vs. afternoon vs. evening)
4. **Unaddressed items** -- things that came up in conversation but didn't get resolved or captured anywhere

## Output

Write analysis to: `~/Edwin/briefing-book/docs/5. Overnight/logs/YYYY-MM-DD-limitless.md`

Format:
```markdown
---
date: YYYY-MM-DD
type: limitless-analysis
segments: [count]
off_calendar: [count]
---

# Limitless Day Review -- YYYY-MM-DD

## Day Overview
[2-3 sentences: what kind of day was it? Heavy meetings? Lots of phone calls? Quiet heads-down?]

## Off-Calendar Conversations
[These are the gold -- conversations Fireflies didn't capture]

### [Time] -- [Brief description]
- **Who:** [participants if identifiable]
- **Key points:** [what was discussed]
- **Action items:** [if any]
- **Context:** [why this matters]

## Emotional Arc
[How was the day from an energy/stress perspective? What moments were high/low?]

## People Map
[Who did the user interact with today and in what context?]

## Tomorrow Context
[What from today should inform tomorrow's brief or Edwin's behavior?]

## PM Items Extracted
[List any new PM items added, or note if none]
```

After writing, publish to Obsidian:
```
python3 briefing-book/scripts/obsidian-publish --all
```

## Completion Report

```
SKILL_COMPLETE: limitless-analysis
STATUS: success | error
ARTIFACT: ~/Edwin/briefing-book/docs/5. Overnight/logs/YYYY-MM-DD-limitless.md
SEGMENTS_REVIEWED: [count]
OFF_CALENDAR: [count]
PM_ITEMS_EXTRACTED: [count]
ERRORS: [any errors, or "none"]
```
