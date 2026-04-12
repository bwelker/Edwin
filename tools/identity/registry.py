#!/usr/bin/env python3
"""
Canonical Identity Registry -- maps all known identifiers to canonical people.

This is the foundation for entity resolution across all Edwin data sources.
Phone numbers, emails, names, handles, and Neo4j UUIDs all resolve to one person.

Usage:
    registry init                          # create/migrate the database
    registry add "Jane Doe"                # add a canonical person
    registry alias <id> name "J. Doe"      # add an alias
    registry alias <id> email "jane@example.com"
    registry alias <id> phone "+15551234567"
    registry resolve "+15551234567"        # who is this?
    registry resolve "J. Doe"              # who is this?
    registry list                          # all canonical people
    registry show <id>                     # show person + all aliases
    registry search "Jane"                 # fuzzy search
    registry stats                         # summary stats
    registry seed-contacts                 # seed from Apple Contacts
"""

import argparse
import os
import sqlite3
import sys
import uuid
from pathlib import Path

DB_PATH = Path(
    os.environ.get(
        "EDWIN_IDENTITY_DB",
        str(Path(__file__).resolve().parent.parent.parent / "data" / "identity" / "registry.db"),
    )
)


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS canonical_people (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            category TEXT DEFAULT 'person' CHECK(category IN ('person', 'organization', 'system')),
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS aliases (
            canonical_id TEXT NOT NULL REFERENCES canonical_people(id) ON DELETE CASCADE,
            alias_type TEXT NOT NULL CHECK(alias_type IN ('name', 'email', 'phone', 'handle', 'neo4j_uuid', 'linear_id', 'jira_id')),
            alias_value TEXT NOT NULL,
            source TEXT,
            confidence REAL DEFAULT 1.0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime')),
            PRIMARY KEY (alias_type, alias_value)
        );

        CREATE INDEX IF NOT EXISTS idx_aliases_canonical ON aliases(canonical_id);
        CREATE INDEX IF NOT EXISTS idx_aliases_value ON aliases(alias_value COLLATE NOCASE);
    """)
    conn.commit()
    conn.close()
    print(f"Registry initialized at {DB_PATH}")


def add_person(name: str, category: str = "person") -> str:
    conn = get_db()
    person_id = str(uuid.uuid4())[:8]
    conn.execute(
        "INSERT INTO canonical_people (id, display_name, category) VALUES (?, ?, ?)",
        (person_id, name, category)
    )
    # Auto-add name as first alias
    conn.execute(
        "INSERT OR IGNORE INTO aliases (canonical_id, alias_type, alias_value, source) VALUES (?, 'name', ?, 'manual')",
        (person_id, name)
    )
    conn.commit()
    conn.close()
    print(f"Added: {name} ({person_id})")
    return person_id


def add_alias(person_id: str, alias_type: str, alias_value: str, source: str = "manual"):
    conn = get_db()
    # Verify person exists
    row = conn.execute("SELECT display_name FROM canonical_people WHERE id = ?", (person_id,)).fetchone()
    if not row:
        print(f"Error: person {person_id} not found", file=sys.stderr)
        sys.exit(1)
    try:
        conn.execute(
            "INSERT INTO aliases (canonical_id, alias_type, alias_value, source) VALUES (?, ?, ?, ?)",
            (person_id, alias_type, alias_value, source)
        )
        conn.commit()
        print(f"Added alias: {alias_type}={alias_value} -> {row['display_name']} ({person_id})")
    except sqlite3.IntegrityError:
        print(f"Alias already exists: {alias_type}={alias_value}", file=sys.stderr)
    conn.close()


def resolve(identifier: str) -> dict | None:
    conn = get_db()
    # Try exact match first (case-insensitive)
    row = conn.execute("""
        SELECT p.id, p.display_name, p.category, a.alias_type, a.alias_value
        FROM aliases a JOIN canonical_people p ON a.canonical_id = p.id
        WHERE a.alias_value = ? COLLATE NOCASE
    """, (identifier,)).fetchone()
    if row:
        result = {"id": row["id"], "name": row["display_name"], "category": row["category"],
                  "matched_on": f"{row['alias_type']}={row['alias_value']}"}
        conn.close()
        return result

    # Try phone number normalization (strip formatting)
    cleaned = identifier.replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if cleaned != identifier:
        row = conn.execute("""
            SELECT p.id, p.display_name, p.category, a.alias_type, a.alias_value
            FROM aliases a JOIN canonical_people p ON a.canonical_id = p.id
            WHERE a.alias_value = ? AND a.alias_type = 'phone'
        """, (cleaned,)).fetchone()
        if row:
            result = {"id": row["id"], "name": row["display_name"], "category": row["category"],
                      "matched_on": f"phone={row['alias_value']}"}
            conn.close()
            return result

    conn.close()
    return None


def list_people():
    conn = get_db()
    rows = conn.execute("""
        SELECT p.id, p.display_name, p.category, COUNT(a.alias_value) as alias_count
        FROM canonical_people p LEFT JOIN aliases a ON p.id = a.canonical_id
        GROUP BY p.id ORDER BY p.display_name
    """).fetchall()
    for r in rows:
        print(f"  {r['id']}  {r['display_name']} ({r['category']}, {r['alias_count']} aliases)")
    print(f"\n{len(rows)} people in registry")
    conn.close()


def show_person(person_id: str):
    conn = get_db()
    person = conn.execute("SELECT * FROM canonical_people WHERE id = ?", (person_id,)).fetchone()
    if not person:
        print(f"Not found: {person_id}", file=sys.stderr)
        sys.exit(1)
    print(f"  Name: {person['display_name']}")
    print(f"  Category: {person['category']}")
    print(f"  Created: {person['created_at']}")
    if person['notes']:
        print(f"  Notes: {person['notes']}")
    print(f"  Aliases:")
    aliases = conn.execute("SELECT * FROM aliases WHERE canonical_id = ? ORDER BY alias_type", (person_id,)).fetchall()
    for a in aliases:
        conf = f" (conf={a['confidence']})" if a['confidence'] < 1.0 else ""
        print(f"    {a['alias_type']}: {a['alias_value']} [src: {a['source']}{conf}]")
    conn.close()


def search(query: str):
    conn = get_db()
    rows = conn.execute("""
        SELECT DISTINCT p.id, p.display_name, p.category, a.alias_type, a.alias_value
        FROM canonical_people p JOIN aliases a ON p.id = a.canonical_id
        WHERE a.alias_value LIKE ? COLLATE NOCASE OR p.display_name LIKE ? COLLATE NOCASE
        ORDER BY p.display_name
    """, (f"%{query}%", f"%{query}%")).fetchall()
    seen = set()
    for r in rows:
        if r['id'] not in seen:
            print(f"  {r['id']}  {r['display_name']} (matched: {r['alias_type']}={r['alias_value']})")
            seen.add(r['id'])
    print(f"\n{len(seen)} matches")
    conn.close()


def stats():
    conn = get_db()
    people = conn.execute("SELECT COUNT(*) as c FROM canonical_people").fetchone()['c']
    aliases = conn.execute("SELECT COUNT(*) as c FROM aliases").fetchone()['c']
    by_type = conn.execute("SELECT alias_type, COUNT(*) as c FROM aliases GROUP BY alias_type ORDER BY c DESC").fetchall()
    print(f"  People: {people}")
    print(f"  Total aliases: {aliases}")
    for r in by_type:
        print(f"    {r['alias_type']}: {r['c']}")
    conn.close()


def _find_contacts_db() -> Path | None:
    """Auto-discover the Apple Contacts database (largest source)."""
    ab_dir = Path.home() / "Library/Application Support/AddressBook/Sources"
    if not ab_dir.exists():
        return None

    best_path = None
    best_count = 0

    for source_dir in ab_dir.iterdir():
        if not source_dir.is_dir():
            continue
        db_file = source_dir / "AddressBook-v22.abcddb"
        if db_file.exists():
            try:
                cdb = sqlite3.connect(str(db_file))
                count = cdb.execute("SELECT COUNT(*) FROM ZABCDRECORD").fetchone()[0]
                cdb.close()
                if count > best_count:
                    best_count = count
                    best_path = db_file
            except Exception:
                continue

    return best_path


def seed_from_contacts():
    """Seed registry from Apple Contacts database."""
    # Allow override via env var, otherwise auto-discover
    env_path = os.environ.get("APPLE_CONTACTS_DB")
    if env_path:
        contacts_db = Path(env_path)
    else:
        contacts_db = _find_contacts_db()

    if not contacts_db or not contacts_db.exists():
        print("Contacts DB not found. Set APPLE_CONTACTS_DB env var or check AddressBook sources.", file=sys.stderr)
        sys.exit(1)

    cdb = sqlite3.connect(str(contacts_db))
    cdb.row_factory = sqlite3.Row

    # Get all contacts with at least a first name
    contacts = cdb.execute("""
        SELECT r.Z_PK, r.ZFIRSTNAME, r.ZLASTNAME, r.ZORGANIZATION
        FROM ZABCDRECORD r
        WHERE r.ZFIRSTNAME IS NOT NULL AND r.ZFIRSTNAME != ''
    """).fetchall()

    reg = get_db()
    init_db()  # ensure tables exist

    added = 0
    skipped = 0
    for c in contacts:
        first = c['ZFIRSTNAME'] or ''
        last = c['ZLASTNAME'] or ''
        display = f"{first} {last}".strip() if last else first

        # Check if already in registry
        existing = reg.execute(
            "SELECT canonical_id FROM aliases WHERE alias_value = ? COLLATE NOCASE AND alias_type = 'name'",
            (display,)
        ).fetchone()
        if existing:
            skipped += 1
            continue

        person_id = str(uuid.uuid4())[:8]
        reg.execute(
            "INSERT INTO canonical_people (id, display_name) VALUES (?, ?)",
            (person_id, display)
        )
        reg.execute(
            "INSERT OR IGNORE INTO aliases (canonical_id, alias_type, alias_value, source) VALUES (?, 'name', ?, 'apple_contacts')",
            (person_id, display)
        )

        # Add phone numbers
        phones = cdb.execute(
            "SELECT ZFULLNUMBER FROM ZABCDPHONENUMBER WHERE ZOWNER = ?", (c['Z_PK'],)
        ).fetchall()
        for p in phones:
            if p['ZFULLNUMBER']:
                cleaned = p['ZFULLNUMBER'].replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
                reg.execute(
                    "INSERT OR IGNORE INTO aliases (canonical_id, alias_type, alias_value, source) VALUES (?, 'phone', ?, 'apple_contacts')",
                    (person_id, cleaned)
                )

        # Add emails
        emails = cdb.execute(
            "SELECT ZADDRESS FROM ZABCDEMAILADDRESS WHERE ZOWNER = ?", (c['Z_PK'],)
        ).fetchall()
        for e in emails:
            if e['ZADDRESS']:
                reg.execute(
                    "INSERT OR IGNORE INTO aliases (canonical_id, alias_type, alias_value, source) VALUES (?, 'email', ?, 'apple_contacts')",
                    (person_id, e['ZADDRESS'].lower())
                )

        added += 1

    reg.commit()
    reg.close()
    cdb.close()
    print(f"Seeded: {added} new people, {skipped} already in registry")


def main():
    parser = argparse.ArgumentParser(description="Canonical Identity Registry")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize database")

    p_add = sub.add_parser("add", help="Add a canonical person")
    p_add.add_argument("name")
    p_add.add_argument("--category", default="person", choices=["person", "organization", "system"])

    p_alias = sub.add_parser("alias", help="Add an alias")
    p_alias.add_argument("person_id")
    p_alias.add_argument("type", choices=["name", "email", "phone", "handle", "neo4j_uuid", "linear_id", "jira_id"])
    p_alias.add_argument("value")
    p_alias.add_argument("--source", default="manual")

    p_resolve = sub.add_parser("resolve", help="Resolve an identifier to a person")
    p_resolve.add_argument("identifier")

    sub.add_parser("list", help="List all people")

    p_show = sub.add_parser("show", help="Show person details")
    p_show.add_argument("person_id")

    p_search = sub.add_parser("search", help="Search by name or alias")
    p_search.add_argument("query")

    sub.add_parser("stats", help="Summary statistics")

    sub.add_parser("seed-contacts", help="Seed from Apple Contacts")

    args = parser.parse_args()

    if args.command == "init":
        init_db()
    elif args.command == "add":
        add_person(args.name, args.category)
    elif args.command == "alias":
        add_alias(args.person_id, args.type, args.value, args.source)
    elif args.command == "resolve":
        result = resolve(args.identifier)
        if result:
            print(f"  {result['name']} ({result['id']}) -- matched on {result['matched_on']}")
        else:
            print(f"  Unknown: {args.identifier}")
    elif args.command == "list":
        list_people()
    elif args.command == "show":
        show_person(args.person_id)
    elif args.command == "search":
        search(args.query)
    elif args.command == "stats":
        stats()
    elif args.command == "seed-contacts":
        seed_from_contacts()


if __name__ == "__main__":
    main()
