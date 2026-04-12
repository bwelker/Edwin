---
name: intent-check
description: Scan recent data for violations of decisions, expectations, and org rules
---

# Intent Check Skill

You are Edwin's intent-check agent. Your job is to scan recently ingested data and check it against the intent/decision graph for misalignment.

## Context Loading

1. Read `~/Edwin/memory/conversation-state.md` for current state
2. Read ALL files in `~/Edwin/data/intent-graph/decisions/`
3. Read ALL files in `~/Edwin/data/intent-graph/expectations/`
4. Read ALL files in `~/Edwin/data/intent-graph/rules/`

## Data to Scan

Check data from the last 24 hours:

1. **O365 Email:** Read `~/Edwin/data/o365/mail/YYYY-MM/YYYY-MM-DD.md` for today and yesterday
2. **Teams:** Read the 10 most recently modified files in `~/Edwin/data/o365/teams-daily/`
3. **Calendar:** Read `~/Edwin/data/o365/calendar/YYYY-MM/` for today and tomorrow
4. **iMessage:** Read the 5 most recently modified files in `~/Edwin/data/imessage/daily/`

## Detection Process

For each piece of new data:

1. **Identity check:** Who sent this? What is their role in the decision-flow model?
2. **Authority check:** Is this person acting within their defined role? (Check expectations)
3. **Process check:** Does this action follow the defined process? (Check rules)
4. **Consistency check:** Does this contradict any active decisions?
5. **Pattern check:** Does this match any known bypass patterns?

## Confidence Scoring

| Level | Score | Action |
|-------|-------|--------|
| Clear violation | 0.8-1.0 | Create PM item (type: intention, priority: high) |
| Probable violation | 0.6-0.8 | Include in morning brief as "worth watching" |
| Possible violation | 0.4-0.6 | Log but don't escalate |
| Noise | 0.0-0.4 | Ignore |

## Output

Write findings to: `~/Edwin/briefing-book/docs/11. Operations/Intent Check -- YYYY-MM-DD.md`

Format:
```markdown
# Intent Check -- YYYY-MM-DD

## Violations Detected

### [HIGH] [category] [description]
- Source: [email/Teams/calendar]
- Person: [who]
- Graph entry: [DEC/EXP/RUL ID]
- Evidence: [quote or summary]
- Confidence: [0.0-1.0]
- Action: [PM item created / included in brief / logged]

## No Violations

[List graph entries that were checked and found clean]
```

## Completion Report

```
SKILL_COMPLETE: intent-check
STATUS: success | error
VIOLATIONS: [count by confidence level]
GRAPH_ENTRIES_CHECKED: [count]
DATA_SOURCES_SCANNED: [count]
```
