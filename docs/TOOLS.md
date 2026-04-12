# Edwin Tool Inventory

Reference for every real-time surface Edwin can reach. Use this BEFORE defaulting to the vector store or saying "I don't have access."

**Rule of thumb:** Vector store and knowledge graph are for "what happened in the past." The tools below are for "what's happening RIGHT NOW."

---

## Real-Time Communication Channels

### O365 Graph CLI (Real-Time Queries)
**Path:** `tools/o365/o365`
**What it does:** Full Microsoft Graph API CLI wrapper for ad-hoc real-time queries -- mail search, calendar, Teams, send email, availability, events. Different from the connector (batch sync).
**Commands:**
- `o365 mail --query "search term" --max N --json` -- search Outlook inbox
- `o365 mail --from-user "name" --unread --json` -- filter by sender/status
- `o365 read <message_id_or_search>` -- read full email body
- `o365 send --to "email" --subject "subj" --body "text"` -- send email (Level 2)
- `o365 send --draft --to "email" --subject "subj" --body "text"` -- create draft
- `o365 calendar --from-date "..." --to-date "..." --json` -- view calendar events
- `o365 event --subject "..." --start "..." --end "..." --attendees "..."` -- create events
- `o365 cancel <event_id> [--cancel --comment "..."]` -- delete/cancel event
- `o365 teams --query "..." --max N --json` -- search Teams chats
- `o365 messages <chat_id> --from-user "..." --max N` -- get messages from a chat
- `o365 teams-send --chat-id "..." --message "..."` -- send Teams messages (delegated auth)
- `o365 availability --users "..." --start "..." --end "..."` -- check free/busy
**Auth:** `~/.edwin/credentials/o365/env` with AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, EDWIN_O365_EMAIL. Delegated token cached at `~/.edwin/credentials/o365/delegated-token.json`.
**When to use:** Email search, reading full email bodies, Teams chat history, calendar checks. FIRST REACH for anything work email/Teams related.

### O365 Connector (Batch Sync)
**Path:** `connectors/o365/o365`
**What it does:** Batch sync of O365 data into Edwin markdown files. Not for ad-hoc queries -- use the Graph CLI above.
**Auth:** Same credentials as the Graph CLI.

### Google Connector (Ad-Hoc Mode)
**Path:** `connectors/google/google`
**What it does:** Live access to Gmail and Google Calendar.
**Commands:**
- `google sync all|mail|calendar` -- incremental sync
- `google auth` -- authenticate with Google
- `google status` -- show sync state
**Auth:** OAuth via `~/.config/edwin/google-token.json`
**When to use:** Personal email, Google Calendar events. Supplement with Gmail MCP for richer search.

### Gmail MCP (Cloud -- available if configured via Claude Code cloud MCP)
**Tool prefix:** `mcp__claude_ai_Gmail__`
**Commands:** `gmail_search_messages`, `gmail_read_message`, `gmail_read_thread`, `gmail_create_draft`, `gmail_list_labels`
**When to use:** Rich Gmail search with full message content. Better than the connector for reading full emails.

### Google Calendar MCP (Cloud -- available if configured via Claude Code cloud MCP)
**Tool prefix:** `mcp__claude_ai_Google_Calendar__`
**Commands:** `gcal_list_calendars`, `gcal_list_events`, `gcal_create_event`, `gcal_update_event`, `gcal_delete_event`, `gcal_find_free_time`, `gcal_find_meeting_times`
**When to use:** All personal calendar operations.

### iMessage (BlueBubbles MCP)
**Tool prefix:** `mcp__bluebubbles__`
**Commands:**
- `bluebubbles_reply` -- send text messages
- `bluebubbles_send_attachment` -- send files/images via iMessage
- `bluebubbles_download_attachment` -- download files sent to Edwin
- `bluebubbles_send_reaction` -- tapback messages (love, like, laugh, etc)
- `bluebubbles_get_messages` -- read message history from a chat
- `bluebubbles_search_chats` -- find/list conversations
**Read (direct):** SQLite database at `~/Library/Messages/chat.db`
**When to use:** iMessage communication, sending/receiving files, reading conversation history.

### Limitless Connector (Ad-Hoc Mode)
**Path:** `connectors/limitless/limitless`
**What it does:** Pull Limitless pendant lifelogs -- transcribed conversations throughout the day.
**Commands:**
- `limitless sync all|lifelogs|chats|audio` -- sync recordings
- `limitless status` -- show last sync times
**Auth:** API key via LIMITLESS_API_KEY
**When to use:** "What was discussed earlier?" "What happened in that conversation?" Ambient intelligence source.

### Fireflies MCP (Cloud -- available if configured via Claude Code cloud MCP)
**Tool prefix:** `mcp__claude_ai_Fireflies__`
**Commands:** `fireflies_search`, `fireflies_get_transcript`, `fireflies_get_summary`, `fireflies_get_transcripts`
**When to use:** Meeting transcripts, who said what, action items from meetings. Search by keyword, date, participants.

---

## Project Management

### Edwin PM (Local MCP)
**Tool prefix:** `mcp__edwin-pm__`
**Commands:** `pm_list`, `pm_add`, `pm_complete`, `pm_search`, `pm_update`
**DB:** `~/Edwin/data/pm/prospective.db`
**When to use:** Personal task/commitment tracker. Due dates, blockers, commitments to/from others.

### Linear MCP (Cloud -- available if configured via Claude Code cloud MCP)
**Tool prefix:** `mcp__claude_ai_Linear__`
**Commands:** `list_issues`, `get_issue`, `save_issue`, `list_projects`, `get_project`, `list_teams`, `list_cycles`, `list_comments`, `save_comment`, `search_documentation`
**When to use:** Linear issues, projects, cycles, comments.

### Atlassian MCP (Cloud -- available if configured via Claude Code cloud MCP)
**Tool prefix:** `mcp__claude_ai_Atlassian_Rovo__`
**Commands:** Jira issues (get, create, edit, transition, search via JQL), Confluence pages (get, create, update, search via CQL), comments
**When to use:** Jira issues, Confluence documentation.

---

## Knowledge & Memory

### Qdrant (Local MCP)
**Tool prefix:** `mcp__edwin-qdrant__`
**Commands:** `memory_search`, `memory_get`, `memory_status`
**Collection:** `edwin-memory` (qwen3-embedding:8b via Ollama)
**URL:** `http://localhost:${QDRANT_PORT:-6380}`
**When to use:** "What did we discuss about X?" Semantic search across all Edwin data. PAST tense -- use real-time tools for current state.

### Neo4j Knowledge Graph (Local MCP)
**Tool prefix:** `mcp__edwin-neo4j__`
**Commands:** `kg_search`, `kg_search_nodes`, `kg_entity_lookup`, `kg_relationships`, `kg_query` (read-only Cypher), `kg_stats`, `kg_write`
**URL:** `bolt://localhost:${NEO4J_BOLT:-7690}`
**When to use:** People relationships, entity connections, multi-hop reasoning ("who reports to who," "what's connected to X project").

---

## Browser & Web

### Chrome DevTools MCP
**Tool prefix:** `mcp__chrome-devtools__`
**Commands:** `list_pages`, `new_page`, `navigate_page`, `take_screenshot`, `take_snapshot`, `click`, `evaluate_script`, `list_console_messages`, `get_console_message`, `list_network_requests`, `get_network_request`, `type_text`, `fill`, `press_key`
**When to use:** Web interaction, debugging, capturing console logs, screenshots, HAR-equivalent data, testing web apps. Available if configured.

### WebSearch / WebFetch
**When to use:** Current information, research, documentation lookup.

---

## External Services

### Brex MCP (Cloud -- available if configured via Claude Code cloud MCP)
**Tool prefix:** `mcp__claude_ai_Brex__`
**When to use:** Expense reports, card management, user lookup.

---

## Local Infrastructure

### Data Connectors (15)
All at `~/Edwin/connectors/{name}/{name} sync [source]`

| Connector | Sources | Output |
|-----------|---------|--------|
| o365 | mail, calendar, teams, sharepoint, onedrive | per-message/event files + per-day teams files |
| google | mail, calendar | per-message/event files |
| imessage | messages | per-day-per-contact files |
| limitless | lifelogs, chats, audio | per-conversation files |
| fireflies | transcripts, audio, video | per-meeting files |
| browser | history (Safari + Chrome) | daily files |
| atlassian | bitbucket, jira, confluence | per-item files |
| notes | notes (Apple Notes) | per-note files |
| photos | metadata | daily files |
| documents | index (Desktop, Documents, iCloud) | file index + extracted text |
| sessions | Claude Code JSONL | per-session files |
| screentime | usage (app usage) | daily files |
| calls | calls (phone call history) | daily files |
| contacts | Apple Contacts | identity registry sync |
| plaud | Plaud Note Pro recordings | per-meeting transcripts |

### Plombery Scheduler
**URL:** `http://localhost:${PLOMBERY_PORT:-8899}`
**What it does:** Web GUI for all scheduled jobs. Built on APScheduler + FastAPI + React.
**Path:** `tools/plombery/app.py`
**Start:** `cd ~/Edwin/tools/plombery && uvicorn app:app --host 0.0.0.0 --port 8899`
**Pipelines:** Connector syncs + indexer + librarian + session watcher + health report + PM export + workspace publish + skills + system tools + backups

### Tools

| Tool | Path | Purpose |
|------|------|---------|
| O365 Graph CLI | `tools/o365/o365` | Microsoft Graph API wrapper -- mail, calendar, Teams, send, events, availability. Ad-hoc real-time queries (not batch sync). |
| Indexer | `tools/indexer/indexer` | Embed markdown into Qdrant (requires Python 3.12). Commands: `sync`, `sync --force`, `sync --dry-run`, `sync --source <name>`, `status`, `verify` |
| Librarian | `tools/librarian/librarian` | Monitor connector freshness, search quality. Commands: `health`, `freshness`, `quality`, `curate`, `full` |
| Identity Registry | `tools/identity/registry.py` | Canonical people database. Commands: `init`, `add`, `alias`, `resolve`, `search`, `list`, `show`, `stats`, `seed-contacts` |
| Session Watcher | `tools/session-watcher/capture` | Monitor session token usage, capture state on idle/threshold. Commands: default, `--force`, `--force-summary` |
| Session Slicer | `tools/session-slicer/session-slicer` | Split Claude Code JSONL logs into 20-min sliding-window time slices for better embedding |
| Systems Report | `tools/systems-report/report` | Health report (API costs, pipeline status, Qdrant, Neo4j). Commands: default, `--stdout`, `--date YYYY-MM-DD` |
| Deep Research | `tools/deep-research/deep-research` | Iterative checkpointed research agent CLI. Commands: `"query"`, `--resume TASK_ID`, `--list`, `--status TASK_ID`. Depths: shallow/medium/deep |

### Briefing Book Scripts
- `briefing-book/scripts/pm-export` -- export PM to Action Tracker markdown, publish to Obsidian
- `briefing-book/scripts/pm-sync` -- sync Obsidian checkbox edits back to PM database
- `briefing-book/scripts/pm-loop` -- full PM <-> Obsidian round-trip (watcher + sync + export)
- `briefing-book/scripts/obsidian-publish --all` -- publish docs to Obsidian vault
- `briefing-book/scripts/obsidian-watcher` -- pull Obsidian vault edits back to docs/
- `briefing-book/scripts/overnight-cleanup` -- archive stale logs/drafts (default 7 days)

### Persistent Services (always-on)
These are infrastructure services, not scheduled jobs:

| Service | How It Runs | Purpose |
|---------|-------------|---------|
| Qdrant | Docker container, localhost:${QDRANT_PORT:-6380} | Vector store |
| Neo4j | Docker container, localhost:${NEO4J_BOLT:-7690} | Knowledge graph |
| Ollama | Native process, localhost:11434 | Local embeddings (qwen3-embedding:8b) |
| Plombery | uvicorn process, localhost:${PLOMBERY_PORT:-8899} | Job scheduler GUI |

---

## LLM Skills (Type C Jobs -- require Claude)

These run via Plombery triggers or on-demand. They invoke Claude to execute a SKILL.md.

**Canonical location:** `~/Edwin/skills/{name}/SKILL.md`
**Index:** `~/Edwin/docs/SKILLS.md` (loaded at boot)

| Skill | Schedule | What It Does |
|-------|----------|-------------|
| **morning-brief** | Weekdays 6 AM | Morning brief with yesterday narrative, calendar, commitments, intel |
| **daily-agenda** | Weekdays 6:05 AM | Daily agenda + per-meeting pre-briefs |
| **monday-prep** | Friday by 2 PM | Status report, talking points, risk radar |
| **overnight-loop** | Daily 9 PM | Nightwatch -- autonomous overnight work session |
| **pm-capture** | Daily 10 PM | Extract commitments/tasks from all channels |
| **limitless-analysis** | Daily 10:30 PM | Deep day review with off-calendar conversation analysis |
| **weekly-dispatch** | Friday 8 PM | Full week retrospective, publish to briefing book |
| **ops-dashboard** | Hourly | Generate operational status pages for briefing book |
| **morning-brief-daily-archive** | Daily 5:55 AM | Archive old morning briefs |
| **weekly-archive** | Monday 5:50 AM | Archive old weekly dispatches |
| **intent-check** | Weekdays 7:30 AM | Scan recent data for decision/expectation violations |
| **pre-1on1-brief** | On-demand | Focused 1:1 meeting prep |

**IMPORTANT:** These produce the Daily Agenda, pre-briefs, and Morning Brief in the Briefing Book. If the output is wrong, the fix is in the SKILL.md. Skills are triggered by Plombery via `run_skill` events to the events channel.

---

## Standalone Tools

| Tool | Path | Purpose | Schedule |
|------|------|---------|----------|
| **email-unanswered** | `tools/email-unanswered/email-unanswered` | Detect unreplied email threads | Weekdays 7:30 AM |
| **teams-unanswered** | `tools/teams-unanswered/teams-unanswered` | Detect unreplied Teams threads | Weekdays 7 AM |
| **pr-monitor** | `tools/pr-monitor/pr-monitor` | Bitbucket PR aging report | Daily 8 AM |
| **pm-wake** | `tools/pm-wake/pm-wake` | Reactivate deferred PM items when due | Daily 6 AM |
| **pm-dedup** | `tools/pm-dedup/pm-dedup` | Detect and cancel near-duplicate PM items | Weekly |
| **pm-recurring** | `tools/pm-recurring/pm-recurring` | Instantiate weekly PM items from templates | Sunday 4 AM |
| **ambient-poll** | `tools/ambient-poll/ambient-poll` | Periodic "what's happening now" snapshots (calendar, Teams, Limitless) | Every 30 min |
| **deep-research** | `tools/deep-research/deep-research` | Iterative checkpointed research agent CLI | Manual (subagent) |
| **contacts** | `connectors/contacts/contacts` | Apple Contacts -> identity registry sync | Weekly |
| **plaud** | `connectors/plaud/plaud` | Plaud Note Pro meeting recordings + transcripts | Daily 9 PM |

---

## Key Paths

- **Briefing Book docs:** `~/Edwin/briefing-book/docs/`
- **Data directory:** `~/Edwin/data/`
- **Connectors:** `~/Edwin/connectors/{name}/{name}`
- **Skills:** `~/Edwin/skills/{name}/SKILL.md`
- **Tools:** `~/Edwin/tools/{name}/`
- **Memory:** `~/Edwin/memory/`
- **PM Database:** `~/Edwin/data/pm/prospective.db`
- **Identity Registry:** `~/Edwin/data/identity/registry.db`
- **iMessage DB:** `~/Library/Messages/chat.db`
- **Credentials:** `~/.edwin/credentials/{service}/env`
- **Plombery GUI:** `http://localhost:${PLOMBERY_PORT:-8899}`
