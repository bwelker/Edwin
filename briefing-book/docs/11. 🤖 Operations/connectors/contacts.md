---
type: connector-docs
connector: contacts
---

# Contacts Connector

Syncs Apple Contacts into the Edwin identity registry for cross-connector name resolution.

## Quick Setup

No configuration needed -- reads directly from macOS. Requires Full Disk Access.

**Database locations:**
```
~/Library/Application Support/AddressBook/AddressBook-v22.abcddb
~/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb
```

## What It Captures

- Contact names (first, middle, last, nickname, organization)
- Phone numbers (normalized to +1XXXXXXXXXX format)
- Email addresses (normalized to lowercase)

This connector does NOT write markdown data files. Instead, it populates the identity registry database used by other connectors (iMessage, Calls) for name resolution.

## How It Works

- Reads all AddressBook SQLite databases (main + per-source)
- Extracts contacts with phone numbers and email addresses
- Normalizes phone numbers (strips formatting, adds +1 prefix for US numbers)
- Normalizes email addresses (lowercase, trimmed)
- Merges into the identity registry at `~/Edwin/data/identity/registry.db`
- Creates/updates canonical_people entries and adds phone/email aliases
- Deduplicates contacts across multiple AddressBook sources

## Output Format

No markdown output. Writes to:
```
~/Edwin/data/identity/registry.db
```

This SQLite database contains:
- `canonical_people` -- display names
- `aliases` -- phone numbers and email addresses linked to people

## Cadence

Weekly via scheduler (Sunday 6 AM).
