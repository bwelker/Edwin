# Connectors

Edwin ships with 15 data connectors that pull your digital life into structured Markdown for embedding and search.

## macOS Native (local databases, no API keys)

| Connector | What it syncs |
|-----------|--------------|
| notes | Apple Notes |
| browser | Safari + Chrome history |
| imessage | iMessage conversations |
| photos | Apple Photos metadata |
| calls | Phone call logs |
| contacts | Apple Contacts |
| screentime | App usage data |
| documents | Desktop, Documents, iCloud files |
| sessions | Claude Code conversation logs |

## API-Based (cross-platform, requires credentials)

| Connector | What it syncs |
|-----------|--------------|
| o365 | Outlook email, calendar, Teams |
| google | Gmail, Google Calendar |
| fireflies | Meeting transcripts |
| limitless | Limitless pendant lifelogs |
| atlassian | Jira, Confluence, Bitbucket |
| plaud | Plaud recording transcripts |

## Platform Notes

macOS-native connectors ship today. Windows/Linux equivalents welcome as PRs -- the connector interface is simple and documented. API-based connectors work on any platform.

For setup instructions, see [Connector Setup](connector-setup.md).
