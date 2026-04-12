---
name: pre-1on1-brief
description: Generate focused prep document before a 1:1 meeting -- last meeting recap, open commitments, what changed, suggested talking points.
---

# Pre-1:1 Brief

Generate a focused preparation document for an upcoming 1:1 meeting. This is deeper than the daily-agenda per-meeting notes -- it includes full context from the last meeting, commitment tracking, and suggested discussion topics.

## Input

The skill receives the meeting context:
- **Person:** Who the user is meeting with
- **Meeting date/time:** When

If no specific meeting is provided, generate briefs for all 1:1 meetings on today's calendar.

## Data Gathering

### 1. Find last meeting with this person
Search meeting transcripts for the most recent meeting involving this person:
```
memory_search "meeting with [person name]" sources=["fireflies"] maxResults=3
```
Also check `data/fireflies/transcripts/` for files with their name.

Read the full transcript and extract:
- Key discussion points
- Decisions made
- Action items / commitments from each side
- Emotional tone / any tension

### 2. Check PM for commitments
```
pm_search "[person name]"
```
Separate into:
- What you owe this person (and status: on track, overdue, etc.)
- What this person owes you (and status)
- Any shared commitments to others

### 3. Recent communications
Search for recent email, Teams, or iMessage exchanges with this person:
```
memory_search "[person name] email teams message" dateFrom=[7 days ago]
```

### 4. KG context
If available, look up the person in the knowledge graph:
```
kg_entity_lookup name="[person name]"
kg_relationships entity="[person name]"
```

### 5. What changed since last meeting
Compare the last meeting date to now. What significant events happened in the interim?
- Read session summaries from that period
- Check for relevant PM items created/completed
- Look for mentions of this person in other meetings

## Output

Write to: `~/Edwin/briefing-book/docs/2. Calendar/1-1 Brief -- [Person Name] -- YYYY-MM-DD.md`

Format:
```markdown
---
date: YYYY-MM-DD
type: pre-1on1-brief
person: [Name]
meeting_time: [HH:MM]
last_meeting: [YYYY-MM-DD]
---

# 1:1 Brief -- [Person Name]

**Meeting:** [Day], [Time] | **Last meeting:** [Date] ([X days ago])

## Last Time

[2-3 sentence summary of what was discussed. Include any unresolved items or tension.]

### Decisions Made
- [decision 1]
- [decision 2]

### Commitments from Last Meeting
| Who | What | Status |
|-----|------|--------|
| You | [item] | [on track / done / overdue] |
| [Person] | [item] | [on track / done / overdue] |

## Since Last Meeting

[What's changed in the interim that's relevant to this person or their domain. New information, decisions made elsewhere, team changes, etc.]

## Open Items

### You Owe [Person]
- [pm-id] [description] -- [status, due date]

### [Person] Owes You
- [pm-id] [description] -- [status, due date]

## Suggested Talking Points

1. **[Topic]** -- [Why it matters, what to ask/say]
2. **[Topic]** -- [Why it matters, what to ask/say]
3. **[Topic]** -- [Why it matters, what to ask/say]

## Tone Notes

[Any observations about this person's current state -- stressed, energized, checked out. Based on recent meeting transcripts and communications. Helps you calibrate your approach.]
```

After writing, publish to Obsidian if configured.

## Completion Report

```
SKILL_COMPLETE: pre-1on1-brief
STATUS: success | error
ARTIFACT: ~/Edwin/briefing-book/docs/2. Calendar/1-1 Brief -- [Person] -- YYYY-MM-DD.md
PERSON: [name]
LAST_MEETING: [date]
OPEN_COMMITMENTS: [count]
ERRORS: [any errors, or "none"]
```
