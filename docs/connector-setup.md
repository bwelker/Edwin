# Connector Setup Guide

How to configure each of Edwin's 15 data connectors.

Credentials are loaded from `~/.edwin/credentials/{service}/env` (preferred) or the project `.env` file (fallback). Each credential file uses `KEY=value` format, one per line.

---

## Section 1: Zero-Config Connectors (macOS Native)

These connectors read directly from local macOS databases and filesystem paths. No API keys, no OAuth, no setup required beyond having the data on your Mac.

### browser

Reads Safari and Chrome browsing history from their local SQLite databases.

- Safari: `~/Library/Safari/History.db`
- Chrome: `~/Library/Application Support/Google/Chrome/Default/History`

No credentials needed. Requires Full Disk Access for the terminal/process running Edwin.

### notes

Reads Apple Notes from the local SQLite database.

- Database: `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`

No credentials needed. Requires Full Disk Access.

### imessage

Reads iMessage/SMS history from the local Messages database.

- Database: `~/Library/Messages/chat.db`

No credentials needed. Requires Full Disk Access.

### photos

Reads photo metadata (not the photos themselves) from the Apple Photos SQLite database.

- Database: `~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite`

No credentials needed. Requires Full Disk Access.

### calls

Reads phone call history from the local CallHistory database.

- Database: `~/Library/Application Support/CallHistoryDB/CallHistory.storedata`

No credentials needed. Requires Full Disk Access.

### contacts

Imports Apple Contacts into the identity registry.

- Reads from the macOS Contacts framework via SQLite.

No credentials needed. Requires Contacts access permission.

### screentime

Reads Screen Time / app usage data from the local knowledge store.

- Database: `~/Library/Application Support/Knowledge/knowledgeC.db`

No credentials needed. Requires Full Disk Access.

### documents

Scans Desktop, Documents, and iCloud Drive for file metadata.

- Paths: `~/Desktop`, `~/Documents`, `~/Library/Mobile Documents/com~apple~CloudDocs`

No credentials needed.

### sessions

Reads Claude Code session JSONL files for embedding and analysis.

- Default path: `~/.claude/projects/` (override with `EDWIN_SESSION_DIR` env var)

No credentials needed.

---

## Section 2: API-Based Connectors

These connectors require API keys, OAuth tokens, or other credentials.

### o365

Syncs Outlook email, calendar, Teams messages, and SharePoint via the Microsoft Graph API.

**Required env vars:**

| Variable | Description |
|----------|-------------|
| `AZURE_TENANT_ID` | Azure AD tenant ID |
| `AZURE_CLIENT_ID` | App registration client ID |
| `AZURE_CLIENT_SECRET` | App registration client secret |
| `EDWIN_EMAIL` | The mailbox email address to sync |

**Credential file:** `~/.edwin/credentials/o365/env`

**How to get credentials:**

1. Go to Azure Portal > App Registrations > New Registration
2. Name it (e.g. "Edwin O365"), set to single tenant
3. Under API Permissions, add Microsoft Graph:
   - `Mail.Read`, `Calendars.Read`, `ChannelMessage.Read.All`, `Chat.Read`, `Sites.Read.All`, `User.Read`
4. Grant admin consent
5. Under Certificates & Secrets, create a new client secret
6. Copy the tenant ID, client ID, and secret value into the credential file

**Token caching:** Tokens are cached at `~/.config/edwin/o365-app-token.json`. Delegated tokens at `~/.config/edwin/o365-delegated-token.json`.

### google

Syncs Gmail and Google Calendar via the Google APIs.

**Required files:**

| Item | Description |
|------|-------------|
| `credentials.json` | OAuth client secret file from Google Cloud Console |
| `google-token.json` | Auto-generated after first OAuth flow |

**Credential paths:**

- OAuth client secret: `~/Library/Application Support/gogcli/credentials.json`
- Token cache: `~/.config/edwin/google-token.json`

**How to get credentials:**

1. Go to Google Cloud Console > APIs & Services > Credentials
2. Create an OAuth 2.0 Client ID (Desktop application type)
3. Download the client secret JSON file
4. Place it at the path above (or use `gog auth credentials /path/to/file`)
5. On first run, the connector opens a browser for OAuth consent
6. Required scopes: Gmail read-only, Calendar read-only

### fireflies

Syncs meeting transcripts from Fireflies.ai.

**Required env vars:**

| Variable | Description |
|----------|-------------|
| `FIREFLIES_API_KEY` | Fireflies API key |

**Credential file:** `~/.edwin/credentials/fireflies/env`

**How to get credentials:**

1. Go to https://app.fireflies.ai/integrations/custom/fireflies
2. Generate an API key
3. Save as `FIREFLIES_API_KEY=your-key-here` in the credential file

### limitless

Syncs lifelog recordings from the Limitless AI pendant.

**Required env vars:**

| Variable | Description |
|----------|-------------|
| `LIMITLESS_API_KEY` | Limitless API key |

**Credential file:** `~/.edwin/credentials/limitless/env`

**How to get credentials:**

1. Open the Limitless app or web dashboard
2. Go to Settings > API
3. Generate a personal API key
4. Save as `LIMITLESS_API_KEY=your-key-here` in the credential file

### atlassian

Syncs Jira issues, Confluence pages, and Bitbucket repositories.

**Required env vars (Jira + Confluence):**

| Variable | Description |
|----------|-------------|
| `ATLASSIAN_EMAIL` | Your Atlassian account email |
| `ATLASSIAN_API_TOKEN` | Atlassian API token |
| `ATLASSIAN_SITE` | Your site name (e.g. `mycompany` for mycompany.atlassian.net) |

**Required env vars (Bitbucket):**

| Variable | Description |
|----------|-------------|
| `BITBUCKET_USERNAME` | Bitbucket username |
| `BITBUCKET_APP_PASSWORD` | Bitbucket app password |
| `BITBUCKET_WORKSPACE` | Bitbucket workspace slug |

**Credential files:**

- `~/.edwin/credentials/atlassian/env` (Jira + Confluence vars)
- `~/.edwin/credentials/bitbucket/env` (Bitbucket vars)

**How to get credentials:**

1. **Atlassian API token:** Go to https://id.atlassian.com/manage-profile/security/api-tokens and create a token
2. **Bitbucket app password:** Go to Bitbucket > Personal Settings > App Passwords, create one with repository read permissions

### plaud

Syncs meeting recordings and transcripts from Plaud Note Pro.

**Required env vars:**

| Variable | Description |
|----------|-------------|
| `PLAUD_TOKEN` | Plaud API authentication token |
| `PLAUD_API_DOMAIN` | API domain (default: `https://api.plaud.ai`) |

**Credential file:** `~/.edwin/credentials/plaud/env`

**How to get credentials:**

1. The Plaud token is obtained from the Plaud app's authenticated session
2. Check the Plaud developer documentation or extract from the app's network traffic
3. Save as `PLAUD_TOKEN=your-token-here` in the credential file

---

## Section 3: Cloud MCP Integrations

> **Note:** If you're on an Anthropic Team or Enterprise plan, your org admin may need to enable cloud MCP integrations in the organization settings before they'll appear. Pro accounts have these enabled by default.

Beyond local connectors, Claude Code has built-in cloud integrations that give Edwin richer real-time access to external services. These run as cloud MCP servers -- no API keys to manage, no credential files. You enable them in Claude Code and they just work.

**How to enable:** In Claude Code, go to **Settings > Integrations** > search for the integration name > enable it. You'll authenticate via OAuth in your browser.

### Gmail (Recommended if you use Google)

Rich email search with full message content, thread reading, and draft creation. The local `google` connector syncs email summaries on a schedule -- the Gmail MCP lets Edwin read full email bodies, search by any criteria, and create drafts in real time. If you use Gmail, this is worth enabling.

### Google Calendar (Recommended if you use Google)

Full calendar CRUD -- create, update, and delete events, find free time slots, check availability. The local `google` connector only reads calendar data on sync. The cloud MCP gives Edwin live read/write access to your calendar during a conversation.

### Linear (If you use Linear)

Issues, projects, cycles, documents, comments. If your team uses Linear for project management, this lets Edwin search issues, create/update tickets, and track cycles without you switching apps.

### Atlassian / Rovo (If you use Jira or Confluence)

Jira issues, Confluence pages, JQL/CQL search, issue creation and transitions. If your team uses Atlassian, this gives Edwin direct access to your project tracker and wiki. Supplements the local `atlassian` connector, which syncs snapshots -- the cloud MCP provides live read/write access.

### Fireflies (If you use Fireflies)

Meeting transcripts, summaries, participant search. The local `fireflies` connector syncs transcripts to disk on a daily schedule. The cloud MCP gives Edwin real-time access to search and read transcripts during a conversation -- useful when you need meeting context immediately after a call.

### Brex (If you use Brex)

Expense reports, card management, spending limits, user lookup. Optional -- only relevant if your company uses Brex for corporate cards and expenses.

---

## Common Environment Variables

These apply across all connectors:

| Variable | Description | Default |
|----------|-------------|---------|
| `EDWIN_HOME` | Root path of the Edwin project | `~/Edwin` |
| `EDWIN_TZ` | Timezone for date handling | `America/New_York` |
| `EDWIN_EMBED_MODEL` | Ollama embedding model name | Set by `setup.sh` |
