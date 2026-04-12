"""Source detection, date extraction, and frontmatter parsing."""

import re
import yaml
from pathlib import Path
from datetime import date

from .config import DATA_DIR, SOURCE_MAP


def detect_source(file_path: Path) -> str:
    """Map file path to source type using SOURCE_MAP.

    Tries 2-part match first (e.g., 'o365/mail'), then 1-part.
    Returns 'default' if no match.
    """
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
    try:
        rel = file_path.relative_to(DATA_DIR)
        return rel.parts[0] if rel.parts else "unknown"
    except ValueError:
        return "unknown"


def extract_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from the start of content.

    Returns empty dict if no frontmatter found.
    """
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    try:
        fm = yaml.safe_load(content[3:end])
        return fm if isinstance(fm, dict) else {}
    except (yaml.YAMLError, ValueError):
        return {}


def extract_date(file_path: Path, frontmatter: dict) -> str | None:
    """Extract date as YYYY-MM-DD string.

    Tries frontmatter 'date' field first, then filename pattern.
    """
    # From frontmatter
    if "date" in frontmatter:
        d = frontmatter["date"]
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
