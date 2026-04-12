# How Edwin Works

A practical guide for day-to-day use. You've finished setup -- here's how to actually get value from this thing.

---

## 1. What Edwin Is

Edwin is a personal AI chief of staff that runs locally on your Mac. It connects to your work tools (email, calendar, messages, meeting transcripts, browser history, notes, and more), pulls that data into structured memory, and gives you an AI agent with real context about your life.

This is not a chatbot. Edwin has access to your actual data -- your emails, your calendar, your messages, your meeting transcripts. When you ask "what did Jason say about the deployment timeline?", Edwin searches across everything it's ingested, not just what you've typed into the current conversation.

You talk to Edwin via **Telegram** (from your phone, tablet, or desktop) or via the **terminal** (`claude` command). Edwin talks back -- proactively, when something matters.

The core idea: a human chief of staff is useful because they're in the room. They hear the same conversations, read the same emails, sit in the same meetings. Edwin does the digital equivalent. The more data sources you connect, the more context Edwin has, and the more useful it becomes.

---

## 2. The Data Loop

This is the mental model that makes everything else make sense.

### How data flows in

**Connectors** pull data from your work tools into markdown files on disk. Each connector targets a specific source:

| Type | Connectors | Credentials needed? |
|------|-----------|---------------------|
| **macOS native** | notes, browser, imessage, photos, calls, contacts, screentime, documents, sessions | No -- reads local databases |
| **API-based** | o365, google, fireflies, limitless, atlassian, plaud | Yes -- API keys or OAuth |

Connectors run on a schedule via **Plombery** (the job scheduler). Email syncs every 15 minutes. Calendar updates regularly. Meeting transcripts pull in after calls. The cadence is configurable.

More connectors configured = more context = smarter assistant. If Edwin can't answer a question, it's usually because the relevant data source isn't connected yet.

### Where data goes

That raw data flows to three places, each serving a different purpose:

**Markdown files** (`data/` directory)
Your raw searchable archive, organized by source and date. Files live at paths like `data/o365/mail/2026-04/2026-04-12.md`. Edwin can read these directly when it needs specific content. You can read them too -- they're just text files.

**Vector database (Qdrant)**
Semantic search across all your data. When you ask "what did we discuss about the Q3 budget?", Qdrant finds the relevant chunks by meaning, not keywords. It understands that "budget discussion" and "financial planning meeting" are related concepts. The **indexer** (`tools/indexer/`) processes your markdown files into Qdrant vectors. It runs hourly by default.

**Knowledge graph (Neo4j)**
Relationships and connections. Who knows who, what project connects to what team, which meeting mentioned which decision. When you need multi-hop reasoning -- "who on my team has worked with the vendor that Sarah mentioned in last week's standup?" -- the knowledge graph is what makes that possible. It builds over time as Edwin processes your data.

### The cycle

```
Connectors sync data --> Markdown files on disk
                              |
                        Indexer runs hourly
                              |
                     Qdrant (semantic search)
                     Neo4j (relationships)
                              |
                    Edwin answers your questions
                    using all three sources
```

---

## 3. The Briefing Book

The briefing book is Edwin's organized output -- reports, summaries, project status, meeting notes, action items. It lives at `briefing-book/docs/` and is designed to be opened with [Obsidian](https://obsidian.md), a free markdown notes app.

Edwin writes to it. You read from it. It's your window into what Edwin knows and has done.

### Sections

| Folder | What's in it |
|--------|-------------|
| **Briefs** | Morning briefings, weekly rollups, situation reports |
| **Calendar** | Today's schedule with context, meeting prep, post-meeting summaries |
| **Action Tracker** | Open commitments, tasks, follow-ups -- what you owe others and what others owe you |
| **Drafts** | Email replies, messages, documents Edwin prepared for your review |
| **Overnight** | Work Edwin did while you slept -- research, maintenance, data processing |
| **Research** | Deep dives on topics you asked about or Edwin flagged as relevant |
| **Projects** | Active project tracking, status, decisions |
| **Products** | Product specs and reference material |
| **People** | Profiles of key people -- communication patterns, relationship context |
| **Daytime Log** | Running log of Edwin's activity during the day |
| **Operations** | System health -- connector status, pipeline metrics, error logs |

You don't organize the briefing book. Edwin does. It fills itself over time as connectors sync, skills run, and you interact. Within a few days of use, it becomes a rich, searchable view of your work life.

**Obsidian makes this significantly better.** Without it, you're reading flat files. With it, you get search, backlinks, graph views, and the ability to sync to your phone via iCloud/Dropbox/Obsidian Sync.

---

## 4. Talking to Edwin

### Via Telegram

If you set up Telegram during onboarding, message your bot from anywhere. It's like texting a very capable assistant who knows your context. Your morning brief arrives before you're out of bed. A commitment you made in a meeting gets flagged while you're driving.

### Via terminal

Run `claude` (with the channel flags if you have Telegram configured). This gives you the full power -- you see everything Edwin sees, you can run commands, and you have direct access to all tools.

With Telegram:
```bash
claude --dangerously-load-development-channels plugin:telegram@claude-plugins-official server:events
```

Without Telegram:
```bash
claude --dangerously-load-development-channels server:events
```

The `server:events` part loads the events channel -- Edwin's internal nervous system for receiving job notifications and skill triggers. Without it, scheduled work silently fails.

### What to ask

Edwin can do anything a chief of staff who reads all your email would do. Some examples:

- "What's on my calendar today?"
- "Any urgent emails since this morning?"
- "What did Jason say about the deployment timeline in yesterday's standup?"
- "Draft a reply to Sarah's email -- tell her we'll have the numbers by Thursday"
- "What do we know about [company/person/topic]?"
- "Remind me to follow up with Pete next Tuesday"
- "Research X and put a summary in my briefing book"
- "What commitments did I make this week?"
- "Prep me for my 2 PM meeting"

**The more specific you are, the better.** "Summarize my emails" works. "What did the sales team flag as blockers in yesterday's thread with Mike?" works much better.

### What Edwin does on its own

Edwin isn't just reactive. With the right skills and schedule configured, it:

- Sends you a morning brief before your day starts
- Extracts action items and commitments from meetings automatically
- Flags overdue commitments
- Runs research overnight while you sleep
- Keeps the briefing book current
- Monitors system health

---

## 5. Tools -- What Edwin Can Reach

Connectors sync data in the background, but Edwin also has real-time tools it can use during a conversation. These fall into three categories.

### Ad-hoc connector commands

The connectors aren't just background sync jobs. Edwin can query them on-demand to answer questions in real time. When you ask "what's on my calendar?" or "did Jason reply?", Edwin runs a connector command and gets a live answer -- not a stale copy from the last sync.

Examples:
- `connectors/o365/o365 mail --query "budget" --max 10` -- search Outlook inbox right now
- `connectors/o365/o365 calendar --today` -- pull today's calendar live
- `connectors/o365/o365 teams --max 20` -- recent Teams messages
- `connectors/o365/o365 availability --email "jason@company.com" --date "2026-04-14"` -- check someone's free/busy
- `connectors/google/google sync mail` -- force a Gmail sync
- `connectors/limitless/limitless sync lifelogs` -- pull latest Limitless recordings

This is often how Edwin answers "did X happen?" questions -- by querying the source directly rather than searching the archive.

### MCP tools

MCP (Model Context Protocol) servers give Edwin native tool access -- functions it can call directly during a conversation, like a programmer calling a library.

**Local MCP servers** (always available):
- **Qdrant** -- semantic search across all indexed data. "What did we discuss about X?" queries go here.
- **Neo4j** -- knowledge graph queries. Relationship lookups, entity connections, multi-hop reasoning.
- **PM** -- prospective memory. Add tasks, check due dates, search commitments.

**Cloud MCP servers** (available if configured via Claude Code):
- **Gmail** -- rich email search with full message content
- **Google Calendar** -- calendar operations, free time search
- **Linear** -- issues, projects, cycles, comments
- **Atlassian** -- Jira issues, Confluence pages, search via JQL/CQL
- **Fireflies** -- meeting transcripts, summaries, participant search
- **Brex** -- expense reports, card management

Cloud MCPs are optional. Edwin works without them, but they add richer access to services where you've configured them. To enable them, go to **Settings > Integrations** in Claude Code, search for the service name (e.g. "Gmail"), and enable it -- you'll authenticate via OAuth in your browser. They're worth it because cloud MCPs give Edwin live read/write access during a conversation, while local connectors only sync snapshots on a schedule. See `docs/connector-setup.md` Section 3 for details on each one.

### Standalone tools

Utility scripts that run as CLI commands. Edwin invokes these when a task calls for specialized logic:

- **email-unanswered** -- find email threads you haven't replied to
- **teams-unanswered** -- find Teams threads awaiting your response
- **pr-monitor** -- Bitbucket PR aging report
- **librarian** -- system health check (connector freshness, search quality)
- **deep-research** -- autonomous research agent with checkpointing
- **identity registry** -- canonical people database (resolve aliases, search contacts)
- **session-watcher** -- monitors your sessions for idle/threshold and triggers auto-summarization
- **systems-report** -- full health report (API costs, pipeline status, Qdrant, Neo4j)
- **pm-wake** / **pm-dedup** / **pm-recurring** -- PM maintenance utilities

These tools are what make Edwin operational rather than just conversational. They're the difference between "I can discuss your email" and "here are the 4 threads you haven't replied to, sorted by urgency."

See `docs/TOOLS.md` for the full tool inventory with commands, paths, and auth requirements.

---

## 6. Prospective Memory (PM)

Edwin tracks what needs to happen -- tasks, commitments, follow-ups, intentions. This is the prospective memory system, backed by a local SQLite database.

### Types of items

| Type | What it means |
|------|--------------|
| **task** | Something that needs to be done |
| **intention** | Something Edwin plans to do (not yet formalized) |
| **commitment_by_user** | A promise you made to someone ("I'll send Pete the plan by Friday") |
| **commitment_to_user** | A promise someone made to you ("Rob said he'd send the numbers") |
| **recurring** | Something that repeats on a schedule |
| **deferred** | Parked for later |

### How it works

- Edwin captures commitments automatically from conversations, meetings, and email
- Items have owners, due dates, priorities, and statuses
- Overdue and due-today items surface in morning briefs and at boot
- You can add items directly: "Remind me to follow up with Sarah next Tuesday"
- You can check status: "What's overdue?" or "What do I owe people this week?"

PM items show up in the **Action Tracker** section of the briefing book as a live checklist.

---

## 7. Skills and Scheduled Work

### What skills are

Skills are packaged workflows -- just markdown files. Each skill lives at `skills/{name}/SKILL.md` and contains step-by-step instructions that teach Edwin how to perform a task. They're human-readable, editable in any text editor, and portable -- any LLM that can read text can execute a skill.

This is Edwin's procedural memory. The vector store knows *what happened*. Skills know *how to do things*.

### Scheduled vs. on-demand

**Scheduled skills** fire automatically via Plombery on a cron trigger. You configure them once and they run forever -- morning briefs at 6 AM, PM capture at 10 PM, ops dashboard every hour. You don't think about them unless something breaks.

**On-demand skills** run when you ask. "Prep me for my 1:1 with Sarah" triggers the pre-1on1-brief skill. "Run nightwatch for 4 hours" triggers the overnight loop. You can also run any scheduled skill on demand -- "run the morning brief now" works fine.

### Available skills

| Skill | What it does | Schedule |
|-------|-------------|----------|
| **morning-brief** | Compiles your day ahead -- calendar, priorities, overnight activity, commitments due | Weekdays 6:00 AM |
| **daily-agenda** | Deep meeting prep for every meeting on today's calendar | Weekdays 6:05 AM |
| **monday-prep** | Status report, talking points, risk radar for leadership meeting | Friday 2:00 PM |
| **ops-dashboard** | System health check -- writes status pages to briefing book | Hourly |
| **pm-capture** | Extracts commitments and tasks from the day's meetings, email, and messages | Daily 10:00 PM |
| **limitless-analysis** | Deep review of ambient conversation recordings | Daily 10:30 PM |
| **weekly-dispatch** | Full week retrospective -- wins, commitments, team signals, red flags | Friday 8:00 PM |
| **overnight-loop** | Autonomous overnight work -- research, maintenance, briefing book updates | Daily 9:00 PM |
| **intent-check** | Scans recent data for decision/expectation violations | Weekdays 7:30 AM |
| **pre-1on1-brief** | Focused 1:1 meeting prep -- last meeting recap, commitments, talking points | On demand |
| **morning-brief-daily-archive** | Archives old morning briefs | Daily 5:55 AM |
| **weekly-archive** | Archives old weekly dispatches | Monday 5:50 AM |

See `docs/SKILLS.md` for detailed descriptions of each skill, including inputs, outputs, and scheduling.

### The overnight loop (nightwatch)

Edwin can work while you sleep. The overnight loop:

1. Reads today's plan (or creates one if none exists)
2. Picks up tasks one at a time -- research, data cleanup, briefing book updates
3. Runs until its stop time (configurable -- typically 4-6 AM)
4. Logs everything to the briefing book's Overnight section

You can start it manually ("run nightwatch for 4 hours") or let it trigger on schedule.

### The job scheduler (Plombery)

Plombery is the scheduler that orchestrates everything. It's a web dashboard at `localhost:8899` that shows:

- Every connector and when it last ran
- Scheduled skills and their triggers
- Run history and any errors
- Manual trigger buttons for forcing a sync

Start it with:
```bash
cd ~/Edwin/tools/plombery && uvicorn app:app --host 0.0.0.0 --port 8899
```

You don't need to check it regularly. It's there when you want to see what's running or troubleshoot why something hasn't updated.

---

## 8. Boot Sequence

When Edwin starts a new session, it doesn't start blank. Here's what happens before it responds to your first message:

1. **Temporal grounding.** Edwin checks the current date, time, and day of week. No guessing at what time it is.
2. **Last session context.** Reads the conversation state from the previous session -- where things left off, what was in progress, what decisions were made.
3. **Capability awareness.** Loads `docs/TOOLS.md` and `docs/SKILLS.md` so it knows what tools are available and what skills it can execute. This is how Edwin knows it can search your email, check your calendar, or run a research agent -- it reads its own capability manifest at startup.
4. **PM check.** Queries the prospective memory system for overdue and due-today items. If you made a commitment yesterday that's due today, Edwin knows about it before you say anything.
5. **Semantic retrieval.** Searches the vector store for context relevant to your first message. If you open with "what happened with the deployment?", Edwin immediately pulls related chunks from past conversations, emails, and meeting transcripts.

This is why Edwin feels like it "remembers" across sessions. It doesn't have persistent memory in the LLM sense -- it reconstructs context at startup from structured state files and semantic search. The quality of that reconstruction depends on how much data has been indexed and how well the previous session was summarized.

---

## 9. Session Lifecycle

Edwin sessions aren't fire-and-forget. Each session feeds the next one.

### During a session

Edwin captures decisions, commitments, open loops, and mental notes inline as the conversation progresses. Commitments get added to PM automatically. Notes get tagged for later retrieval.

### When a session ends

Edwin produces a session summary -- a structured markdown file that captures:
- **Gist** -- what happened, written as if briefing a future version of itself with zero context
- **Decisions** -- what was decided and why
- **Tension map** -- open loops with stakes, what breaks if dropped
- **Commitments** -- what you owe others, what others owe you, what Edwin owes you
- **Key identifiers** -- file paths, URLs, ticket numbers, dollar amounts preserved verbatim

Summaries are written to `memory/sessions/` and get indexed into the vector store on the next indexer run.

### Session-to-session continuity

The next session reads the previous summary during boot (step 2 above). This creates a chain -- each session knows what the last one accomplished, what's still open, and where the conversation would naturally pick up.

The **session-watcher** tool monitors for idle sessions and token thresholds, triggering auto-summarization so context isn't lost even if a session ends abruptly.

Over time, the accumulated session summaries become a rich, searchable log of every decision, commitment, and conversation you've had with Edwin.

---

## 10. How Edwin Gets Smarter

Edwin starts thin. Within hours it gets useful. Within a week it gets good. Here's what compounds:

**Connector data accumulates.** Every sync cycle adds more email, more calendar events, more messages, more meeting transcripts. The pool of searchable context grows continuously.

**Every conversation is indexed.** When you ask Edwin to research something, debug a problem, or make a decision -- that entire exchange becomes searchable context. Next time a related topic comes up, Edwin can draw on what you discussed before. You don't re-explain backstory.

**The knowledge graph builds connections.** As data flows in, entities (people, projects, companies, decisions) get linked. Edwin starts to understand not just what happened, but who was involved, what they committed to, and how things connect.

**Your CLAUDE.md evolves.** The setup wizard generates your initial CLAUDE.md (Edwin's identity and operating rules). As you use Edwin, you refine it -- adjusting autonomy levels, adding behavioral rules, tuning the attention filter. This is Edwin's personality file, and it gets sharper over time.

**Memory files capture preferences.** Edwin records what it learns about you -- communication preferences, working patterns, key relationships -- in memory files that persist across sessions.

The practical effect: conversations get shorter and more useful. Edwin needs less prompting, anticipates better, and answers questions that require cross-referencing multiple sources.

---

## 11. Extending Edwin

Everything in Edwin is files. Markdown, TypeScript, Python. No proprietary formats, no vendor lock-in.

### Add a new connector

Connectors live in `connectors/{name}/`. Each is a standalone Python CLI that pulls data from a source and writes markdown files to `data/`. Look at any existing connector for the pattern. If there's a data source Edwin doesn't support yet -- a platform you use, an API you rely on -- build a connector.

### Create a new skill

Skills live in `skills/{name}/SKILL.md`. Write a plain markdown file with instructions for what Edwin should do, what data to gather, and what output to produce. Schedule it in Plombery or trigger it on demand. The morning-brief skill is a good example to study.

### Build a new MCP tool

MCP (Model Context Protocol) servers give Edwin native tool access. The three built-in servers (Qdrant, Neo4j, PM) are in `mcp-servers/`. Add new ones to expose new capabilities -- a CRM integration, a custom API, a specialized search tool.

### Build a new channel

If Telegram doesn't fit your workflow, build a channel for Slack, WhatsApp, Signal, or whatever you use. The events channel MCP server (`mcp-servers/events-channel/index.ts`) shows the pattern.

---

## 12. Key Commands and Paths

### Directory structure

| Path | What's there |
|------|-------------|
| `data/` | Raw synced data from connectors, organized by source and date |
| `briefing-book/docs/` | The briefing book -- Edwin's organized output (open with Obsidian) |
| `connectors/` | 15 data connectors (Python CLIs) |
| `skills/` | 12 skill definitions (SKILL.md files) |
| `docs/TOOLS.md` | Full tool inventory -- every command Edwin can reach |
| `docs/SKILLS.md` | Skill index -- every workflow Edwin knows how to execute |
| `tools/indexer/` | Embeds markdown into Qdrant for semantic search |
| `tools/plombery/` | Job scheduler with web dashboard |
| `mcp-servers/` | MCP integrations (Qdrant, Neo4j, PM, events channel) |
| `memory/` | Session summaries and memory index |
| `CLAUDE.md` | Edwin's identity and operating instructions |
| `.env` | Configuration (ports, timezone, credentials) |

### Running connectors manually

Any connector can be run directly:
```bash
connectors/o365/o365 sync mail        # sync Outlook email
connectors/browser/browser sync all   # sync Safari + Chrome history
connectors/notes/notes sync all       # sync Apple Notes
connectors/imessage/imessage sync all # sync iMessage
```

### Checking system status

```bash
# Docker containers (Qdrant + Neo4j)
docker ps --filter name=edwin

# Qdrant health
curl -s http://localhost:6380/collections/edwin-memory | python3 -m json.tool

# Ollama models
ollama list

# Plombery dashboard
open http://localhost:8899
```

### Triggering skills manually

In a conversation with Edwin, just say:
- "Run the morning brief"
- "Do an ops check"
- "Run nightwatch for 3 hours"

### Starting Edwin

With Telegram:
```bash
claude --dangerously-load-development-channels plugin:telegram@claude-plugins-official server:events
```

Without Telegram:
```bash
claude --dangerously-load-development-channels server:events
```

### Starting Plombery

```bash
cd ~/Edwin/tools/plombery && uvicorn app:app --host 0.0.0.0 --port 8899
```

---

## What to do next

1. **Open the briefing book** in Obsidian (`briefing-book/docs/`). The Action Tracker has your setup tasks.
2. **Start Plombery** so connectors run on schedule and skills fire automatically.
3. **Connect more data sources.** Each connector you enable gives Edwin more context. Start with the ones that matter most to your workflow.
4. **Use it.** Ask Edwin questions. Give it tasks. The more you interact, the more it learns about your world. Every conversation gets indexed.
5. **Tune your CLAUDE.md** over time. Adjust autonomy levels, add behavioral rules, refine the attention filter. This is Edwin's personality -- make it yours.
