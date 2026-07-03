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
| triage-pass | "What needs you" sweep of what's new since the last pass -- surfaces only the 2-3 items needing your judgment | Every few hours (workday) | Message push |
| reply-drafts | Ready-to-paste reply drafts for high-priority + key-contact stale threads, in your voice. Drafts only, never sends | Weekday mornings | briefing-book/docs/4. Drafts/ |
| pre-decision-brief | Decision radar -- detect decisions approaching in the next few days, build evidence-backed dossiers before the moment | Weekdays | briefing-book/docs/2. Calendar/ |
| decision-ledger | Harvest decisions actually made in the week's meetings, track follow-through, surface quietly-dying decisions | Weekly | data/decisions/ + briefing book |
| pm-weekly-triage | Evidence-based grooming pass over the PM backlog -- auto-close on hard evidence, re-date own stragglers, propose the rest | Weekly | PM database + proposal doc |
| kg-curation | Knowledge-graph maintenance -- freshness sweep, stale-edge invalidation, merge-queue drain, org-chart completeness | Weekly | Neo4j + run record |
| self-study | Corpus distillation -- read one high-value corpus end-to-end, write a synthesis study file for retrieval | On-demand / nightwatch | memory/distilled/ |
| self-retro | Grade Edwin's own performance against a fixed rubric; land corrections as mechanical checks/harness edits | Weekly | memory/ + briefing book |
| devils-advocate | Red-team your active big bets -- the evidence-backed case AGAINST each, ending in KILL/HEDGE/PROCEED-EYES-OPEN | Monthly (first Saturday) | briefing-book/docs/1. Briefs/ |

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

### triage-pass
Recurring work-hours "what needs you" sweep that complements the morning brief. Scans only what is NEW since the last pass (watermark state), and surfaces ONLY the 2-3 items that genuinely need your judgment or action -- everything else is dropped. Pushed via the messaging channel by the orchestrator, not written to the briefing book. A clean pass (nothing surfaced) is a valid outcome.

### reply-drafts
Draft-first email posture. Takes the morning's high-priority email plus key-contact threads going stale and produces ready-to-paste reply drafts in your voice. The judgment (what to say) is Edwin's; the plumbing (which emails, where drafts land) is deterministic. HARD RULE: this skill drafts only -- it never sends. The output is a markdown file you edit-and-send or discard.

### pre-decision-brief
Decision radar plus dossier generator. Detects decisions approaching you in the next few business days (from calendar, email, threads) and builds an evidence-backed dossier BEFORE the moment -- prior positions, stakeholder map, constraining commitments, and what the decision gates. Not meeting prep: it preps the choice, not the time slot. Uses an authority model (`docs/decision-flow-model.md`) as its lens if one exists.

### decision-ledger
Meeting-to-closure decision tracking. Harvests decisions actually MADE in the last week's meetings, maintains a persistent ledger (`data/decisions/ledger.jsonl`), verifies downstream follow-through evidence, and surfaces decisions that are quietly dying at the two-week mark. Grades reality, not intentions -- a discussion or a "we'll probably" is not a decision. Complements pm-capture (which owns commitments) and pre-decision-brief (which owns decisions still approaching).

### pm-weekly-triage
Standing weekly grooming pass over the prospective-memory backlog so it self-grooms instead of rotting. Two auto-execute moves only: close items that have hard, cited completion evidence, and re-date still-live items Edwin owns. Everything else is written to a strike-and-approve proposal doc for you -- it never auto-closes on "looks stale." The safe closes happen every run regardless of whether the proposal is read.

### kg-curation
Weekly knowledge-graph maintenance loop for Neo4j. Runs a freshness sweep against the week's reality, invalidates stale edges, drains the pending-merge queue, and checks org-chart temporal completeness against the authority model. All fact writes go through the provenance tools with a real source_ref; skip-when-thin discipline and per-pass write caps keep the curated graph clean. Reports doc-vs-reality mismatches; never edits the authority model itself.

### self-study
Corpus distillation. Hybrid retrieval finds chunks but misses synthesis questions that span dozens of files ("how do all the decisions on this project fit together"). This skill reads one high-value, stable corpus end-to-end and writes a distilled study file to `memory/distilled/<corpus-id>.md`, where the indexer embeds it with a query-time boost. Picks the stalest corpus from a registry; one corpus per run (depth over coverage). Runs as a nightwatch task or standalone.

### self-retro
Weekly self-retrospective. Grades Edwin's own performance over the past 7 days against a fixed rubric, re-scores past lessons for actual behavioral gain, and lands corrections as mechanical checks or harness edits first (prose memory only as a fallback). Deliberately hunts under-action (flags missed, replies never sent, deferrals) as hard as over-action. Grades Edwin, never the user.

### devils-advocate
Monthly red-team pass over your active big bets. Builds the strongest evidence-backed case AGAINST each position you're invested in -- steelmanned opposition drawn from your own corpus, not strawman compliance -- and ends each bet with an honest KILL / HEDGE / PROCEED-EYES-OPEN verdict. The case FOR already has a full-time advocate (you). Lands in the briefing book as a weekend read; not pushed to the messaging channel.
