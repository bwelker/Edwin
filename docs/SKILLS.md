# Edwin Skills Index

Procedural memory -- portable SKILL.md files. Each skill is a self-contained instruction set any LLM can execute.

| Skill | What It Does | Schedule | Output |
|-------|-------------|----------|--------|
| morning-brief | Morning briefing -- yesterday narrative, calendar, commitments, intel | Weekdays 6 AM | briefing-book/docs/1. Briefs/ |
| daily-agenda | Daily agenda + per-meeting pre-briefs with research | Weekdays 6:05 AM | briefing-book/docs/2. Calendar/ |
| monday-prep | Status report, talking points, risk radar for leadership meeting | Friday by 2 PM | briefing-book/docs/1. Briefs/ |
| overnight-loop | Nightwatch planner -- prioritized task list for overnight autonomous work | Daily 9 PM | data/nightwatch/ |
| pm-capture | Extract commitments/tasks from meetings, email, Teams, iMessage | Daily 10 PM | PM database |
| limitless-analysis | Deep review of Limitless recordings -- off-calendar conversations, insights | Daily 10:30 PM | briefing-book/docs/5. Overnight/ |
| weekly-dispatch | Full week retrospective -- wins, commitments, signals, red flags | Friday 8 PM | briefing-book/docs/1. Briefs/ |
| ops-dashboard | Operational status pages -- pipeline health, indexing, memory, capabilities | Hourly | briefing-book/docs/11. Operations/ |
| morning-brief-daily-archive | Archive old morning briefs to Daily Archive folder | Daily 5:55 AM | briefing-book/docs/1. Briefs/Daily Archive/ |
| weekly-archive | Archive old weekly dispatches to Weekly Archive folder | Monday 5:50 AM | briefing-book/docs/1. Briefs/Weekly Archive/ |
| intent-check | Scan recent data for decision/expectation/rule violations | Weekdays 7:30 AM | briefing-book/docs/1. Briefs/ |
| pre-1on1-brief | Focused 1:1 meeting prep -- last meeting recap, commitments, talking points | On-demand | briefing-book/docs/2. Calendar/ |

Skills are read on demand, not at boot. This index tells Edwin what's available. To execute: read the SKILL.md and follow the instructions.

**Scheduling:** Skills are triggered by Plombery via `run_skill` events to the events channel. The orchestrator receives the event, spawns a subagent, and the subagent executes the SKILL.md. Each skill returns a Completion Report.

**Canonical location:** `~/Edwin/skills/{name}/SKILL.md`

---

## Skill Details

### morning-brief
Generate comprehensive morning briefing covering yesterday's narrative (what happened across all channels), today's calendar, open commitments, intel items. Pulls from session summaries, email, Teams, iMessage, Limitless, Fireflies, calendar. Self-checks for accuracy before publishing.

### daily-agenda
Daily agenda with per-meeting pre-briefs. Archives yesterday's prep first. For each meeting, researches participants, recent context, open items, and suggested talking points. Heavier research than morning-brief's calendar section.

### monday-prep
Friday automation for the weekly leadership meeting. Compiles status from project management (Linear, Jira), dev daily updates, and recent session context. Produces talking points and risk areas.

### overnight-loop (nightwatch)
Plans the overnight autonomous work session. Assesses the landscape (PM items, open loops, system health, pending research) and produces a ranked task list. The orchestrator handles execution -- spawning subagents for each task until the stop time.

### pm-capture
Nightly sweep of all communication channels (Fireflies transcripts, email, Teams, iMessage, Limitless, calendar) to extract commitments and tasks that weren't captured during live sessions. Deduplicates against existing PM items before adding.

### limitless-analysis
Deep review of Limitless pendant recordings. Catches things formal meeting tools miss -- hallway conversations, phone calls, thinking-out-loud moments. Extracts insights, commitments, and context for tomorrow.

### weekly-dispatch
Full week retrospective covering wins, open commitments, team signals, decisions made, red flags, and next week preview. Draws from session summaries, PM items, and all data sources for the week.

### ops-dashboard
Generates 4 operational status pages: Pipeline Status (connector health), Indexing Status (vector coverage), Memory Health (Qdrant, Neo4j, Ollama, PM), and Capabilities (skills, pipelines, MCP servers).

### morning-brief-daily-archive
Housekeeping skill. Moves morning briefs with yesterday's date (or older) from the active Briefs folder to Daily Archive. Publishes to Obsidian.

### weekly-archive
Housekeeping skill. Moves weekly dispatches from prior weeks into the Weekly Archive folder. Publishes to Obsidian.

### intent-check
Scans recently ingested data against the intent/decision graph for misalignment. Checks decisions, expectations, and organizational rules stored in `data/intent-graph/`. Flags violations.

### pre-1on1-brief
On-demand deep prep for 1:1 meetings. Finds last meeting with the person, reviews commitments made/received, checks what's changed since, and suggests talking points. Deeper than daily-agenda's per-meeting notes.
