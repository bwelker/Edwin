---
name: monday-prep
description: Friday Monday-prep automation -- compile status report, talking points, and risk areas for the weekly leadership meeting
trigger: Friday by 2 PM
---

Compile the Monday prep package for your weekly leadership meeting: status report + talking points + risk areas.

## Identity

Read `~/Edwin/docs/identity/SOUL.md` for your voice. Direct, opinionated, dry. You synthesize -- you don't list raw data. Think like a tech leader briefing the executive team.

## Context Loading

Before anything:

1. Run `date "+%A, %B %d, %Y"` to get today's date. Confirm it's Friday. If not Friday, note the deviation but proceed.
2. Read `~/Edwin/memory/conversation-state.md` for current context
3. Read the 2 most recent `~/Edwin/memory/sessions/*-summary.md` files for this week's narrative

## Data Gathering

Run ALL of these. Missing data is fine -- work with what you have. **Do not fabricate tickets, names, or status.**

### Project Tracker (Linear, JIRA, or equivalent)

Use your project management MCP tools:

1. Find active projects and teams. Note their IDs.
2. Get all issues updated this week. For each issue, capture:
   - Issue identifier (e.g. PROJ-128)
   - Title
   - Status (Todo, In Progress, In Review, Done, Cancelled)
   - Assignee
   - Priority
   - Labels
3. Group issues by status: **Shipped** (Done this week), **In Progress**, **In Review/QA**, **Blocked**
4. Check current sprint health (items planned vs completed vs remaining)

If you use multiple project trackers (e.g., Linear + JIRA), repeat for each and merge the results.

### Team Status Updates

Read any team status update channels (e.g., Teams, Slack, standup notes):
- Check `~/Edwin/data/` for relevant team communication files
- Read the most recent entries to get this week's developer/team status updates
- Extract: who's working on what, what shipped, what's blocked, what's planned

### Email & Calendar Context

- Scan this week's email data for messages from leadership, escalations, client issues
- Check Monday's calendar -- what meetings are scheduled?
- Look for emails from key stakeholders flagging issues

### Semantic Memory

- `memory_search` for: "leadership priority", "executive concern", "leadership request" -- surface what leadership has been asking about
- `memory_search` for: "blocker", "risk", "escalation" -- surface open risks
- `pm_list` with filter "due" -- check for overdue/due items that leadership might ask about

## Compilation

Write THREE documents:

### Document 1: Status Report

**Output:** `~/Edwin/briefing-book/docs/1. Briefs/Software Dev Status -- Week of YYYY-MM-DD.md`

Format (match the established template exactly):

```markdown
# Software Development Status -- Week of [Monday date]

**Prepared for:** [Leadership] | **From:** [Your name] | **Period:** [Mon] -- [Fri], [Year]

---

## Executive Summary

[3-5 bullet points. Lead with wins (shipped count, key deliverables). Then current state (what's in flight). Then blockers/risks. Be specific with numbers. Leadership wants to see velocity and health, not process detail.]

---

## Key Projects Status

| Project | Health | Notes |
|---------|--------|-------|
| [Project] | [On Track / Watch / At Risk / Starting] | [One-line status] |

[Include all active projects. 4-8 rows.]

---

## Who's Working on What

| Team Member | Current Work |
|-------------|-------------|
| [Name] | [What they shipped + what they're on now. Be specific with ticket numbers.] |

[Include every team member who posted updates this week.]

---

## Risks / Blockers

[2-4 paragraph narrative. What could derail next week? What needs leadership attention? What's blocked on cross-team coordination? QA throughput? Be honest.]

---

## Detail (Appendix)

### Shipped This Week ([count] items)

[List each: ticket number -- description -- assignee. Group by project/tracker.]

### In Review / QA

**In Review ([count])**
[List each with assignee]

**In QA ([count])**
[List each with assignee]

### Added Mid-Sprint ([count])
[List items added after sprint start]
```

### Document 2: Monday Talking Points

**Output:** `~/Edwin/briefing-book/docs/1. Briefs/Monday Talking Points -- YYYY-MM-DD.md`

```markdown
# Monday Talking Points -- [date]

## Leadership's Likely Questions
[Based on this week's emails, drive-bys, and known concerns -- what will leadership ask about? Prep concise answers.]

## Wins to Lead With
[What looks good? What can you point to as evidence of velocity?]

## Risks to Get Ahead Of
[What bad news is coming? Better to surface it proactively than let leadership discover it.]

## Ask Leadership For
[What do you need from them? Decisions, resources, air cover?]

## Pipeline Status
[What PRDs or initiatives are in the pipeline? Who owes what? What's ready to prioritize?]
```

### Document 3: Leadership Risk Radar

**Output:** `~/Edwin/briefing-book/docs/1. Briefs/Leadership Risk Radar -- YYYY-MM-DD.md`

```markdown
# Leadership Risk Radar -- [date]

[Short doc. What are the things leadership might escalate? For each:]

## [Risk Name]
- **What:** [the situation]
- **Why leadership cares:** [connect to their known concerns -- growth, client commitments, velocity]
- **Current state:** [facts]
- **Your position:** [what to say if asked]
- **Worst case:** [what happens if this goes sideways]
```

## Publishing

1. Write all three documents to the briefing book paths above
2. Publish to Obsidian if configured (e.g., run `~/Edwin/briefing-book/scripts/obsidian-publish`)
3. If the conversation is live (not a scheduled task), notify the user: "Monday prep package ready in the briefing book. Three docs: status report, talking points, leadership risk radar."

## Quality Rules

- **No fabricated data.** If you can't find a ticket, don't invent one. If a team member didn't post updates, note the gap.
- **Ticket numbers must be real.** Cross-reference every ticket number against the project tracker data you pulled.
- **Names must be real.** Only use team member names from status updates or issue assignees.
- **No em dashes.** Use `--` instead.
- **Be honest about what you don't know.** "Data unavailable" is better than a guess.
- **Steelman as the executive.** After writing the status report, reread it as if you were the executive reading it Monday morning. What questions would they ask? Make sure the report answers them.
