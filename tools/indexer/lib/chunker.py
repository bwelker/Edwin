"""Source-aware chunking pipeline.

Strategies:
  - speaker:  Preserve speaker turns (iMessage, Limitless)
  - email:    Preserve email headers, one email = one doc
  - teams:    Multiple frontmatter blocks per file, group messages
  - sections: Section-based splitting for structured docs (Fireflies)
  - turns:    Turn-based splitting for sessions (## Turn N)
  - header:   Markdown header-aware splitting (Jira, Confluence)
  - default:  Line-based with overlap
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import CHUNK_CONFIG, CHARS_PER_TOKEN
from .metadata import detect_source, extract_frontmatter, split_multi_frontmatter


@dataclass
class Chunk:
    text: str
    start_line: int
    end_line: int
    metadata: dict = field(default_factory=dict)


def chunk_file(content: str, source_type: str, file_path: Path) -> list[Chunk]:
    """Main entry point. Dispatches to the right strategy."""
    cfg = CHUNK_CONFIG.get(source_type, CHUNK_CONFIG["default"])
    strategy = cfg["strategy"]
    max_chars = cfg["tokens"] * CHARS_PER_TOKEN
    overlap_chars = cfg["overlap"] * CHARS_PER_TOKEN

    # Strip frontmatter from content for chunking (metadata extracted separately)
    body = _strip_frontmatter(content)

    if not body.strip():
        return []

    if strategy == "teams":
        return _chunk_teams(content, max_chars, overlap_chars)
    elif strategy == "speaker":
        return _chunk_speaker(body, max_chars, overlap_chars)
    elif strategy == "email":
        return _chunk_email(body, max_chars, overlap_chars)
    elif strategy == "sections":
        return _chunk_sections(body, max_chars, overlap_chars)
    elif strategy == "turns":
        return _chunk_turns(body, max_chars, overlap_chars)
    elif strategy == "header":
        return _chunk_header(body, max_chars, overlap_chars)
    else:
        return _chunk_default(body, max_chars, overlap_chars)


def _strip_frontmatter(content: str) -> str:
    """Remove the first frontmatter block, return the rest."""
    if not content.startswith("---"):
        return content
    end = content.find("\n---", 3)
    if end == -1:
        return content
    return content[end + 4:].strip()


def _lines_to_chunks(lines: list[str], start_offset: int, max_chars: int,
                     overlap_chars: int) -> list[Chunk]:
    """Group lines into chunks respecting size limits."""
    chunks = []
    current_lines = []
    current_len = 0
    chunk_start = start_offset

    for i, line in enumerate(lines):
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > max_chars and current_lines:
            text = "\n".join(current_lines)
            chunks.append(Chunk(
                text=text,
                start_line=chunk_start,
                end_line=chunk_start + len(current_lines) - 1,
            ))
            # Overlap: keep trailing lines that fit in overlap
            overlap_lines = []
            overlap_len = 0
            for ol in reversed(current_lines):
                if overlap_len + len(ol) + 1 > overlap_chars:
                    break
                overlap_lines.insert(0, ol)
                overlap_len += len(ol) + 1

            chunk_start = chunk_start + len(current_lines) - len(overlap_lines)
            current_lines = list(overlap_lines)
            current_len = overlap_len

        current_lines.append(line)
        current_len += line_len

    if current_lines:
        text = "\n".join(current_lines)
        chunks.append(Chunk(
            text=text,
            start_line=chunk_start,
            end_line=chunk_start + len(current_lines) - 1,
        ))

    return chunks


# -- Strategy: Teams (multiple frontmatter blocks) --------------------------

def _chunk_teams(content: str, max_chars: int, overlap_chars: int) -> list[Chunk]:
    """Teams files have multiple frontmatter blocks. Group messages into chunks."""
    segments = split_multi_frontmatter(content)

    # Each segment is a frontmatter + message. Extract just the message text.
    messages = []
    for seg in segments:
        body = _strip_frontmatter(seg).strip()
        if body:
            messages.append(body)

    if not messages:
        return []

    # Group messages into chunks by size
    chunks = []
    current = []
    current_len = 0

    for msg in messages:
        msg_len = len(msg) + 2  # +2 for separator
        if current_len + msg_len > max_chars and current:
            chunks.append(Chunk(
                text="\n\n".join(current),
                start_line=0,
                end_line=0,
            ))
            # Overlap: keep last message(s) that fit
            overlap = []
            olen = 0
            for m in reversed(current):
                if olen + len(m) + 2 > overlap_chars:
                    break
                overlap.insert(0, m)
                olen += len(m) + 2
            current = list(overlap)
            current_len = olen

        current.append(msg)
        current_len += msg_len

    if current:
        chunks.append(Chunk(
            text="\n\n".join(current),
            start_line=0,
            end_line=0,
        ))

    return chunks


# -- Strategy: Speaker turns (iMessage, Limitless) --------------------------

def _chunk_speaker(body: str, max_chars: int, overlap_chars: int) -> list[Chunk]:
    """Split on speaker labels (bold name patterns like **Name** (time):)."""
    # Split on speaker labels, keeping the label with its content
    parts = re.split(r'(?=\*\*[^*]+\*\*\s*\()', body)
    parts = [p.strip() for p in parts if p.strip()]

    if not parts:
        return _chunk_default(body, max_chars, overlap_chars)

    # Group speaker turns into chunks
    chunks = []
    current = []
    current_len = 0

    for part in parts:
        part_len = len(part) + 2
        if current_len + part_len > max_chars and current:
            chunks.append(Chunk(
                text="\n\n".join(current),
                start_line=0,
                end_line=0,
            ))
            overlap = []
            olen = 0
            for t in reversed(current):
                if olen + len(t) + 2 > overlap_chars:
                    break
                overlap.insert(0, t)
                olen += len(t) + 2
            current = list(overlap)
            current_len = olen

        current.append(part)
        current_len += part_len

    if current:
        chunks.append(Chunk(
            text="\n\n".join(current),
            start_line=0,
            end_line=0,
        ))

    return chunks


# -- Strategy: Email --------------------------------------------------------

def _chunk_email(body: str, max_chars: int, overlap_chars: int) -> list[Chunk]:
    """Email: single file = single email. Chunk by paragraphs/sections."""
    lines = body.split("\n")
    return _lines_to_chunks(lines, 0, max_chars, overlap_chars)


# -- Strategy: Sections (Fireflies) -----------------------------------------

def _chunk_sections(body: str, max_chars: int, overlap_chars: int) -> list[Chunk]:
    """Split on H2/H3 headers, keeping each section together if it fits."""
    sections = re.split(r'(?=^#{2,3}\s)', body, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    if not sections:
        return _chunk_default(body, max_chars, overlap_chars)

    chunks = []
    for section in sections:
        if len(section) <= max_chars:
            chunks.append(Chunk(text=section, start_line=0, end_line=0))
        else:
            # Section too large, fall back to line-based
            lines = section.split("\n")
            chunks.extend(_lines_to_chunks(lines, 0, max_chars, overlap_chars))

    return chunks


# -- Strategy: Turns (Sessions) ---------------------------------------------

def _chunk_turns(body: str, max_chars: int, overlap_chars: int) -> list[Chunk]:
    """Split on ## Turn N headers."""
    turns = re.split(r'(?=^## Turn \d+)', body, flags=re.MULTILINE)
    turns = [t.strip() for t in turns if t.strip()]

    if not turns:
        return _chunk_default(body, max_chars, overlap_chars)

    chunks = []
    current = []
    current_len = 0

    for turn in turns:
        turn_len = len(turn) + 2
        if current_len + turn_len > max_chars and current:
            chunks.append(Chunk(
                text="\n\n".join(current),
                start_line=0,
                end_line=0,
            ))
            # Keep last turn as overlap
            overlap = []
            olen = 0
            for t in reversed(current):
                if olen + len(t) + 2 > overlap_chars:
                    break
                overlap.insert(0, t)
                olen += len(t) + 2
            current = list(overlap)
            current_len = olen

        current.append(turn)
        current_len += turn_len

    if current:
        chunks.append(Chunk(
            text="\n\n".join(current),
            start_line=0,
            end_line=0,
        ))

    return chunks


# -- Strategy: Header (Jira, Confluence, documents) -------------------------

def _chunk_header(body: str, max_chars: int, overlap_chars: int) -> list[Chunk]:
    """Split on markdown headers (any level), keeping header with content."""
    sections = re.split(r'(?=^#{1,4}\s)', body, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    if not sections:
        return _chunk_default(body, max_chars, overlap_chars)

    chunks = []
    current = []
    current_len = 0

    for section in sections:
        sec_len = len(section) + 2
        if current_len + sec_len > max_chars and current:
            chunks.append(Chunk(
                text="\n\n".join(current),
                start_line=0,
                end_line=0,
            ))
            overlap = []
            olen = 0
            for s in reversed(current):
                if olen + len(s) + 2 > overlap_chars:
                    break
                overlap.insert(0, s)
                olen += len(s) + 2
            current = list(overlap)
            current_len = olen

        current.append(section)
        current_len += sec_len

    if current:
        chunks.append(Chunk(
            text="\n\n".join(current),
            start_line=0,
            end_line=0,
        ))

    return chunks


# -- Strategy: Default (line-based) -----------------------------------------

def _chunk_default(body: str, max_chars: int, overlap_chars: int) -> list[Chunk]:
    """Simple line-based chunking with overlap."""
    lines = body.split("\n")
    return _lines_to_chunks(lines, 0, max_chars, overlap_chars)
