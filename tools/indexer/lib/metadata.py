"""Source detection, date extraction, and frontmatter parsing."""

import re
import yaml
from pathlib import Path
from datetime import date

from .config import DATA_DIR, MEMORY_DIR, SOURCE_MAP


def _is_memory_file(file_path: Path) -> bool:
    try:
        file_path.relative_to(MEMORY_DIR)
        return True
    except ValueError:
        return False


def detect_source(file_path: Path) -> str:
    """Map file path to source type using SOURCE_MAP.

    Tries 2-part match first (e.g., 'o365/mail'), then 1-part.
    Files under MEMORY_DIR are source 'memory'.
    Returns 'default' if no match.
    """
    if _is_memory_file(file_path):
        return "memory"
    try:
        rel = file_path.relative_to(DATA_DIR)
    except ValueError:
        return "default"

    parts = rel.parts
    if len(parts) >= 2:
        two_part = f"{parts[0]}/{parts[1]}"
        if two_part in SOURCE_MAP:
            return SOURCE_MAP[two_part]
    if parts[0] in SOURCE_MAP:
        return SOURCE_MAP[parts[0]]
    return "default"


def detect_connector(file_path: Path) -> str:
    """Get the top-level connector directory name."""
    if _is_memory_file(file_path):
        return "memory"
    try:
        rel = file_path.relative_to(DATA_DIR)
        return rel.parts[0] if rel.parts else "unknown"
    except ValueError:
        return "unknown"


def _fallback_frontmatter(block: str) -> dict:
    """Line-wise 'key: value' parse for frontmatter that isn't valid YAML.

    Roughly half the jira files have unquoted values like
    'type: [System] Incident' that make yaml.safe_load throw, which used
    to silently discard the ENTIRE frontmatter (dates, status, assignee).
    Values are kept as raw strings.
    """
    fm = {}
    for line in block.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm


def extract_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from the start of content.

    Falls back to a line-wise key:value parse when the block isn't valid
    YAML. Returns empty dict if no frontmatter found.
    """
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    block = content[3:end]
    try:
        fm = yaml.safe_load(block)
        return fm if isinstance(fm, dict) else _fallback_frontmatter(block)
    except (yaml.YAMLError, ValueError):
        return _fallback_frontmatter(block)


def extract_date(file_path: Path, frontmatter: dict) -> str | None:
    """Extract date as YYYY-MM-DD string.

    Tries frontmatter date-ish fields first ('date', then 'updated'/
    'modified'/'created' -- jira/confluence issues carry those instead of
    'date'), then filename pattern, then parent dir (YYYY-MM).
    """
    # From frontmatter: 'date' preferred, then last-activity fields.
    # Jira files (data/atlassian/jira/) have created/updated but no 'date';
    # 'updated' is the retrieval-relevant one (48,954 points were invisible
    # to every dateFrom/dateTo filter before this fallback -- 2026-07-02).
    for field in ("date", "updated", "modified", "created"):
        if field not in frontmatter:
            continue
        d = frontmatter[field]
        if isinstance(d, date):
            return d.isoformat()
        s = str(d)
        m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
        if m:
            return m.group(1)

    # From filename (YYYY-MM-DD.md)
    m = re.match(r"(\d{4}-\d{2}-\d{2})", file_path.stem)
    if m:
        return m.group(1)

    # From parent dir (YYYY-MM)
    m = re.match(r"(\d{4}-\d{2})", file_path.parent.name)
    if m:
        return m.group(1) + "-01"

    return None


def extract_channel(file_path: Path, source: str) -> str | None:
    """Extract channel/subcategory from path.

    For Teams: 'oneOnOne' or 'group'
    For iMessage: 'conversations' or 'group'
    For others: sub-path component if present.
    """
    try:
        rel = file_path.relative_to(DATA_DIR)
    except ValueError:
        return None

    parts = rel.parts

    if source == "o365-teams" and len(parts) >= 3:
        return parts[2]  # e.g., 'oneOnOne', 'group'
    if source == "imessage" and len(parts) >= 2:
        return parts[1]  # e.g., 'conversations'
    if source == "fireflies" and len(parts) >= 2:
        return parts[1]  # e.g., 'transcripts'
    if source == "limitless" and len(parts) >= 2:
        return parts[1]  # e.g., 'lifelogs'

    return None


def extract_payload_fields(frontmatter: dict) -> dict:
    """Extract optional payload fields from frontmatter for Qdrant storage."""
    fields = {}
    for key in ("subject", "from", "participants", "title", "speakers",
                "assignee", "status", "priority", "project", "space"):
        if key in frontmatter and frontmatter[key] is not None:
            fields[key] = str(frontmatter[key])
    return fields


def split_multi_frontmatter(content: str) -> list[str]:
    """Split a file with multiple frontmatter blocks into segments.

    Used for Teams files where each message has its own frontmatter.
    Returns list of segments, each starting with '---'.
    If the file has only one frontmatter block, returns [content].
    """
    # Count frontmatter blocks
    # Pattern: line starting with --- that begins a YAML block
    parts = re.split(r'\n(?=---\n)', content)

    # First part might start with ---
    if content.startswith("---"):
        segments = [parts[0]]
        segments.extend(parts[1:])
    else:
        segments = parts

    # Filter out empty segments
    segments = [s.strip() for s in segments if s.strip()]

    # If we only got one segment, it's a single-frontmatter file
    if len(segments) <= 1:
        return [content]

    return segments
