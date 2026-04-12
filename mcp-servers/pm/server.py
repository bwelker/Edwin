#!/usr/bin/env python3
"""
Edwin Prospective Memory MCP Server

Exposes Edwin's task/commitment tracking system (SQLite) to Claude Code.
Provides list, add, complete, update, and search operations.

Tools:
  pm_list     — list items with filters (due, overdue, type, owner, status)
  pm_add      — add a new item (task, commitment, intention, etc.)
  pm_complete — mark an item as done
  pm_update   — update an item's fields
  pm_search   — search items by description text

Transport: stdio
"""

import hashlib
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

DB_PATH = Path(
    os.environ.get(
        "PM_DB_PATH",
        str(Path(os.environ.get("EDWIN_HOME", str(Path.home() / "Edwin"))) / "data/pm/prospective.db"),
    )
)

VALID_TYPES = [
    "intention",
    "task",
    "commitment_by_user",
    "commitment_to_user",
    "recurring",
    "deferred",
]
VALID_STATUSES = ["open", "in_progress", "waiting", "blocked", "scheduled", "done", "cancelled", "overdue"]
VALID_PRIORITIES = ["critical", "high", "medium", "low"]

mcp = FastMCP("edwin-pm")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _generate_id(description: str) -> str:
    h = hashlib.sha256(
        (description + str(datetime.now().timestamp())).encode()
    ).hexdigest()[:6]
    return f"pm-{h}"


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def _format_items(rows: list[sqlite3.Row]) -> str:
    if not rows:
        return "No items found."

    today = date.today()
    lines = []
    for r in rows:
        d = dict(r)
        item_id = d["id"]
        desc = d["description"]
        status = d["status"]
        item_type = d["type"]
        owner = d.get("owner", "")
        due = d.get("due_date", "")
        priority = d.get("priority", "")
        counterparty = d.get("counterparty", "")

        # Due status indicator
        due_marker = ""
        if due and status not in ("done", "cancelled"):
            try:
                due_date = date.fromisoformat(due)
                if due_date < today:
                    due_marker = " OVERDUE"
                elif due_date == today:
                    due_marker = " DUE TODAY"
            except ValueError:
                pass

        parts = [f"[{item_id}] {desc}"]
        parts.append(f"  type={item_type} status={status}")
        if owner:
            parts.append(f"owner={owner}")
        if counterparty:
            parts.append(f"counterparty={counterparty}")
        if priority:
            parts.append(f"priority={priority}")
        if due:
            parts.append(f"due={due}{due_marker}")

        lines.append(" | ".join(parts))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def pm_list(
    filter: str = "open",
    type: Optional[str] = None,
    owner: Optional[str] = None,
    counterparty: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 50,
) -> str:
    """List prospective memory items.

    Args:
        filter: One of: open (default), due, overdue, due_today, due_this_week, all, done
        type: Filter by type: intention, task, commitment_by_user, commitment_to_user, recurring, deferred
        owner: Filter by owner name (e.g. "user", "edwin")
        counterparty: Filter by counterparty name
        tag: Filter by tag
        limit: Max items to return (default 50)
    """
    conn = _get_conn()
    cursor = conn.cursor()

    where = []
    params: list = []

    today = date.today()

    if filter == "open":
        where.append("items.status IN ('open', 'in_progress', 'waiting')")
    elif filter == "due":
        where.append(
            "items.due_date <= ? AND items.status NOT IN ('done', 'cancelled')"
        )
        params.append(today.isoformat())
    elif filter == "overdue":
        where.append(
            "items.due_date < ? AND items.status NOT IN ('done', 'cancelled')"
        )
        params.append(today.isoformat())
    elif filter == "due_today":
        where.append("items.due_date = ?")
        params.append(today.isoformat())
    elif filter == "due_this_week":
        week_end = today + timedelta(days=(6 - today.weekday()))
        where.append("items.due_date BETWEEN ? AND ?")
        params.extend([today.isoformat(), week_end.isoformat()])
        where.append("items.status NOT IN ('done', 'cancelled')")
    elif filter == "done":
        where.append("items.status = 'done'")
    elif filter == "all":
        pass  # no status filter
    else:
        where.append("items.status IN ('open', 'in_progress', 'waiting')")

    if type:
        where.append("items.type = ?")
        params.append(type)
    if owner:
        where.append("items.owner = ?")
        params.append(owner)
    if counterparty:
        where.append("items.counterparty = ?")
        params.append(counterparty)
    if tag:
        where.append("items.id IN (SELECT item_id FROM tags WHERE tag = ?)")
        params.append(tag)

    where_clause = (" WHERE " + " AND ".join(where)) if where else ""
    query = f"SELECT * FROM items{where_clause} ORDER BY due_date ASC NULLS LAST, created_at DESC LIMIT ?"
    params.append(limit)

    rows = cursor.execute(query, params).fetchall()
    conn.close()

    return _format_items(rows)


@mcp.tool()
def pm_add(
    description: str,
    type: str = "task",
    owner: str = "user",
    counterparty: str = "",
    due_date: str = "",
    priority: str = "",
    context: str = "",
    source: str = "session conversation",
    source_date: str = "",
    external_ref: str = "",
    tags: str = "",
) -> str:
    """Add a new prospective memory item.

    Args:
        description: What needs to be done
        type: One of: intention, task, commitment_by_user, commitment_to_user, recurring, deferred
        owner: Who owns this (default "user")
        counterparty: Who the commitment is with (optional)
        due_date: ISO date (YYYY-MM-DD), "today", or "tomorrow" (optional)
        priority: critical, high, medium, or low (optional)
        context: Additional context about the item (optional)
        source: Where this came from (default "session conversation")
        source_date: When the source event happened, ISO date (optional, defaults to today)
        external_ref: External reference like "linear:BRA-75" (optional)
        tags: Comma-separated tags (optional)
    """
    if type not in VALID_TYPES:
        return f"Error: type must be one of {VALID_TYPES}"
    if priority and priority not in VALID_PRIORITIES:
        return f"Error: priority must be one of {VALID_PRIORITIES}"

    # Resolve due date
    resolved_due = None
    if due_date:
        if due_date == "today":
            resolved_due = date.today().isoformat()
        elif due_date == "tomorrow":
            resolved_due = (date.today() + timedelta(days=1)).isoformat()
        else:
            try:
                date.fromisoformat(due_date)
                resolved_due = due_date
            except ValueError:
                return "Error: due_date must be YYYY-MM-DD, 'today', or 'tomorrow'"

    if not source_date:
        source_date = date.today().isoformat()

    conn = _get_conn()
    cursor = conn.cursor()

    item_id = _generate_id(description)
    # Handle collisions
    while cursor.execute("SELECT id FROM items WHERE id = ?", (item_id,)).fetchone():
        item_id = _generate_id(description + str(datetime.now().timestamp()))

    cursor.execute(
        """INSERT INTO items (id, type, owner, counterparty, description, context,
           source, source_date, due_date, priority, external_ref)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item_id,
            type,
            owner,
            counterparty or None,
            description,
            context or None,
            source,
            source_date,
            resolved_due,
            priority or None,
            external_ref or None,
        ),
    )

    if tags:
        for tag in [t.strip() for t in tags.split(",") if t.strip()]:
            cursor.execute(
                "INSERT INTO tags (item_id, tag) VALUES (?, ?)", (item_id, tag)
            )

    conn.commit()
    conn.close()

    due_str = f" (due {resolved_due})" if resolved_due else ""
    return f"Added [{item_id}]: {description}{due_str}"


@mcp.tool()
def pm_complete(item_id: str) -> str:
    """Mark a prospective memory item as done.

    Args:
        item_id: The item ID (e.g. "pm-a3f8c2")
    """
    conn = _get_conn()
    cursor = conn.cursor()

    row = cursor.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        conn.close()
        return f"Error: item {item_id} not found"

    now = datetime.now().isoformat(timespec="seconds")
    cursor.execute(
        "UPDATE items SET status = 'done', completed_at = ?, updated_at = ? WHERE id = ?",
        (now, now, item_id),
    )
    conn.commit()
    conn.close()

    return f"Completed [{item_id}]: {row['description']}"


@mcp.tool()
def pm_update(
    item_id: str,
    status: str = "",
    due_date: str = "",
    priority: str = "",
    description: str = "",
    context: str = "",
    owner: str = "",
    counterparty: str = "",
) -> str:
    """Update fields on a prospective memory item.

    Args:
        item_id: The item ID (e.g. "pm-a3f8c2")
        status: New status: open, in_progress, waiting, done, cancelled, overdue
        due_date: New due date (YYYY-MM-DD, "today", "tomorrow")
        priority: New priority: critical, high, medium, low
        description: New description
        context: New context
        owner: New owner
        counterparty: New counterparty
    """
    conn = _get_conn()
    cursor = conn.cursor()

    row = cursor.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if not row:
        conn.close()
        return f"Error: item {item_id} not found"

    updates = []
    params: list = []

    if status:
        if status not in VALID_STATUSES:
            conn.close()
            return f"Error: status must be one of {VALID_STATUSES}"
        updates.append("status = ?")
        params.append(status)
        if status == "done":
            updates.append("completed_at = ?")
            params.append(datetime.now().isoformat(timespec="seconds"))

    if due_date:
        if due_date == "today":
            resolved = date.today().isoformat()
        elif due_date == "tomorrow":
            resolved = (date.today() + timedelta(days=1)).isoformat()
        else:
            try:
                date.fromisoformat(due_date)
                resolved = due_date
            except ValueError:
                conn.close()
                return "Error: due_date must be YYYY-MM-DD, 'today', or 'tomorrow'"
        updates.append("due_date = ?")
        params.append(resolved)

    if priority:
        if priority not in VALID_PRIORITIES:
            conn.close()
            return f"Error: priority must be one of {VALID_PRIORITIES}"
        updates.append("priority = ?")
        params.append(priority)

    if description:
        updates.append("description = ?")
        params.append(description)

    if context:
        updates.append("context = ?")
        params.append(context)

    if owner:
        updates.append("owner = ?")
        params.append(owner)

    if counterparty:
        updates.append("counterparty = ?")
        params.append(counterparty)

    if not updates:
        conn.close()
        return "No fields to update."

    updates.append("updated_at = ?")
    params.append(datetime.now().isoformat(timespec="seconds"))
    params.append(item_id)

    cursor.execute(
        f"UPDATE items SET {', '.join(updates)} WHERE id = ?", params
    )
    conn.commit()
    conn.close()

    return f"Updated [{item_id}]"


@mcp.tool()
def pm_search(query: str, limit: int = 20) -> str:
    """Search prospective memory items by description text.

    Args:
        query: Text to search for in descriptions (case-insensitive)
        limit: Max results (default 20)
    """
    conn = _get_conn()
    cursor = conn.cursor()

    rows = cursor.execute(
        "SELECT * FROM items WHERE description LIKE ? ORDER BY created_at DESC LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    conn.close()

    return _format_items(rows)


if __name__ == "__main__":
    mcp.run(transport="stdio")
