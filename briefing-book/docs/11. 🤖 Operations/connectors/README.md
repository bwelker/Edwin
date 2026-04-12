---
type: connector-index
---

# Edwin Connectors

15 data connectors syncing work and life data into markdown files for LLM ingestion and embedding. Each connector is a standalone Python CLI at `~/Edwin/connectors/{name}/{name}`.

## Quick Reference

### Local Connectors (No Credentials Needed)

These read directly from macOS databases and filesystems. Only requirement is Full Disk Access.

| Connector | What It Does | Data Source | Cadence |
|-----------|-------------|-------------|---------|
| [imessage](imessage.md) | iMessage/SMS conversations | Messages chat.db | 60-120 min |
| [browser](browser.md) | Safari + Chrome history | History databases | 2 hr |
| [calls](calls.md) | Phone/FaceTime call log | CallHistory (iCloud sync) | daily 9 PM |
| [screentime](screentime.md) | App usage durations | KnowledgeC.db | daily 9 PM |
| [notes](notes.md) | Apple Notes | NoteStore.sqlite | 2 hr |
| [photos](photos.md) | Photo/video metadata + GPS | Photos.sqlite | daily 9 PM |
| [documents](documents.md) | Text extraction from files | Desktop, Docs, iCloud | daily 9 PM |
| [sessions](sessions.md) | Claude Code session logs | ~/.claude/projects/*.jsonl | 2 hr |
| [contacts](contacts.md) | Apple Contacts to identity DB | AddressBook databases | weekly Sun 6 AM |

### API/OAuth Connectors (Credentials Required)

These need API keys, OAuth tokens, or app registrations. See each doc for setup instructions.

| Connector | What It Does | Auth Type | Cadence |
|-----------|-------------|-----------|---------|
| [o365](o365.md) | Email, calendar, Teams, SharePoint | Azure AD OAuth | 15-60 min |
| [google](google.md) | Gmail, Google Calendar | Google OAuth | 30-120 min |
| [limitless](limitless.md) | Pendant lifelogs + Ask AI chats | API key | 1 hr |
| [fireflies](fireflies.md) | Meeting transcripts | API key | daily 9 PM |
| [atlassian](atlassian.md) | Bitbucket, Jira, Confluence | API token + app password | 2-8 hr |
| [plaud](plaud.md) | Voice recordings + transcripts | Bearer token | daily |

## Common Patterns

All connectors share these design patterns:

- **CLI interface**: `{name} sync all|{source} [--since N] [--reset] [--verbose]` and `{name} status`
- **State tracking**: `.sync-state.json` in each data directory for incremental sync
- **File locking**: `.sync.lock` with `fcntl.flock()` prevents concurrent runs
- **Atomic writes**: temp file + `os.replace()` prevents corruption on crash
- **Dedup**: SHA1 id-hashes embedded in output files prevent duplicate entries
- **Credential lookup**: `~/.edwin/credentials/{service}/env` (preferred), then `~/Edwin/.env` (fallback), then environment variables

## Common Commands

```bash
# Sync everything for a connector
./connectors/{name}/{name} sync all

# Check sync status
./connectors/{name}/{name} status

# Force backfill from N days ago
./connectors/{name}/{name} sync all --since 90

# Reset state and re-sync
./connectors/{name}/{name} sync all --reset --since 30

# Verbose output
./connectors/{name}/{name} sync all --verbose
```

## Credential Locations

```
~/.edwin/credentials/
  o365/env          # AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, EDWIN_EMAIL
  atlassian/env     # ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN, ATLASSIAN_SITE
  bitbucket/env     # BITBUCKET_USERNAME, BITBUCKET_APP_PASSWORD, BITBUCKET_WORKSPACE
  limitless/env     # LIMITLESS_API_KEY
  fireflies/env     # FIREFLIES_API_KEY
  plaud/env         # PLAUD_TOKEN, PLAUD_API_DOMAIN
```

Google OAuth token is stored separately at `~/.config/edwin/google-token.json`.

## Data Output Root

All connector output goes under `~/Edwin/data/{connector}/` with month-based subdirectories (`YYYY-MM/`).
