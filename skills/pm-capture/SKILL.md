---
name: pm-capture
description: Extract commitments, tasks, and action items from today's meetings, email, Teams, and iMessage. Deduplicate against existing PM items and add new ones.
---

# PM Capture

Nightly sweep of all communication channels to extract commitments and tasks that weren't captured during live sessions. Runs daily at 10 PM.

## Why This Exists

Commitments made in meetings, email threads, and chats often don't get tracked. Edwin captures some during live sessions, but anything that happens when Edwin isn't active gets missed. This skill fills that gap by reviewing the day's raw data and extracting PM-worthy items.

## Data Sources (Today Only)

Process these in parallel. For each source, read today's data only.

### 1. Fireflies transcripts
Read `data/fireflies/transcripts/YYYY-MM/YYYY-MM-DD-*.md` for today.
- These are meeting transcripts with full speaker attribution.
- Look for: "I'll do X", "can you do X by Y", "let's plan to", "we need to", "action item", "follow up on", "I committed to", "I owe you"
- Attribute the commitment to the speaker.

### 2. Limitless lifelogs
Read `data/limitless/lifelogs/YYYY-MM/YYYY-MM-DD-*.md` for today.
- These capture ambient conversations including off-calendar meetings.
- Same extraction patterns as Fireflies.
- Lower confidence -- ambient capture is noisier.

### 3. O365 email
Read `data/o365/mail/YYYY-MM/YYYY-MM-DD-*.md` for today.
- Look for: requests made to the user, commitments the user made in replies, deadlines mentioned, "please review by", "let me know by", "I'll send you"
- Focus on emails TO and FROM the user, not CC/newsletter.

### 4. Teams messages
Read `data/o365/teams/` -- check file mtimes for today's activity.
- Look for direct requests, commitments, blockers mentioned, deadline references.

### 5. iMessage
Read `data/imessage/daily/` for today's files.
- Personal commitments, family logistics, social obligations.
- Be selective -- most iMessage is casual. Only capture clear commitments.

## Extraction Rules

For each potential PM item:

1. **Confidence threshold:** Only extract if >70% confident this is a real commitment or task. Casual mentions, jokes, hypotheticals, "we should probably..." are NOT PM items.

2. **Dedup check:** Before adding, call `pm_search` with the description text. If a similar item already exists (open or in_progress), skip it. Log the skip.

3. **Attribution:**
   - Who owns it? (the person who said they'd do it)
   - Who's the counterparty? (who they committed to)
   - What's the due date? (explicit if stated, infer from context: "this week" = end of week, "tomorrow" = tomorrow, "before the meeting" = meeting date)
   - What's the priority? (high if it's a commitment to the CEO/leadership, medium otherwise, low for personal/nice-to-have)

4. **Type mapping:**
   - The user says "I'll do X" -> `commitment_by_user`
   - Someone says "I'll do X for the user" -> `commitment_to_user`
   - The user assigns "can you do X" -> `task` (owner = assignee)
   - General "we need to do X" with no clear owner -> `intention` (owner = user unless context says otherwise)

5. **Context:** Include the source (meeting name, email subject, chat) and a brief quote showing the commitment. This makes the item verifiable.

## Output

For each extracted item, call `pm_add` with the appropriate fields.

Write a capture log to: `~/Edwin/data/nightwatch/pm-capture-YYYY-MM-DD.log`

Format:
```
# PM Capture Log -- YYYY-MM-DD

## Sources Scanned
- Fireflies: X transcripts
- Limitless: X lifelogs
- O365 mail: X emails
- Teams: X messages
- iMessage: X conversations

## Items Captured
1. [pm-id] [type] [owner] -> [counterparty] | [description] | Source: [source]
2. ...

## Items Skipped (duplicate)
1. [description] -- matches [existing-pm-id]
2. ...

## Items Skipped (low confidence)
1. [description] -- [why low confidence]
2. ...

## Summary
Captured: X new items
Skipped: X duplicates, X low-confidence
Sources: X transcripts, X emails, X chats
```

## Completion Report

```
SKILL_COMPLETE: pm-capture
STATUS: success | error
ARTIFACT: ~/Edwin/data/nightwatch/pm-capture-YYYY-MM-DD.log
ITEMS_CAPTURED: [count]
ITEMS_SKIPPED_DUP: [count]
ITEMS_SKIPPED_LOW: [count]
SOURCES_SCANNED: [count]
ERRORS: [any errors, or "none"]
```
