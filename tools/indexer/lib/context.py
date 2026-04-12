"""Contextual retrieval via Anthropic Haiku with prompt caching.

For each chunk, generates a 50-100 token context prefix that situates
the chunk within its parent document. The context is prepended to the
chunk text before embedding.
"""

import os
import sys
import time

from .config import (ANTHROPIC_MODEL, ANTHROPIC_RETRIES,
                     CONTEXT_MIN_DOC_TOKENS, CONTEXT_SOURCE_THRESHOLDS,
                     CONTEXT_SLIDING_WINDOW, CONTEXT_SEGMENT_SOURCES,
                     CONTEXT_PROMPT, CHARS_PER_TOKEN, CREDENTIALS_FILE)


def _load_api_key() -> str | None:
    """Load Anthropic API key from env or credentials file."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key

    if CREDENTIALS_FILE.exists():
        for line in CREDENTIALS_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
            if line.startswith("export ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    return None


class ContextGenerator:
    """Generate contextual retrieval prefixes using Haiku."""

    def __init__(self):
        self.api_key = _load_api_key()
        self._client = None
        self.enabled = self.api_key is not None

        if not self.enabled:
            print("WARNING: No Anthropic API key found. "
                  "Contextual retrieval disabled.", file=sys.stderr)
            print(f"  Set ANTHROPIC_API_KEY env var or add to {CREDENTIALS_FILE}",
                  file=sys.stderr)

    @staticmethod
    def _build_sliding_window(document: str, file_path, window_size: int) -> str:
        """Build a sliding window document by including messages from adjacent day files.

        For per-day files (e.g., teams-daily/Dev Daily Update/2026-04-02.md),
        loads the last N messages from the previous day and first N messages
        from the next day, prepending/appending to the current document.
        """
        from pathlib import Path
        from datetime import datetime, timedelta

        file_path = Path(file_path)
        # Parse date from filename (expected: YYYY-MM-DD.md)
        try:
            day = datetime.strptime(file_path.stem, "%Y-%m-%d")
        except ValueError:
            return document  # Not a daily file, skip window

        prev_day = day - timedelta(days=1)
        next_day = day + timedelta(days=1)

        # Look for adjacent files in same directory or adjacent month directories
        def find_day_file(dt):
            # Same directory
            same_dir = file_path.parent / f"{dt.strftime('%Y-%m-%d')}.md"
            if same_dir.exists():
                return same_dir
            # Adjacent month directory (e.g., going from April 1 to March 31)
            month_dir = file_path.parent.parent / dt.strftime("%Y-%m")
            if month_dir.exists():
                alt = month_dir / f"{dt.strftime('%Y-%m-%d')}.md"
                if alt.exists():
                    return alt
            return None

        def extract_messages(text, count, from_end=False):
            """Extract N messages from start or end. Messages are separated by ---."""
            blocks = [b.strip() for b in text.split("---\n") if b.strip()]
            if from_end:
                blocks = blocks[-count:]
            else:
                blocks = blocks[:count]
            return "\n---\n".join(blocks)

        parts = []

        # Previous day: last N messages
        prev_file = find_day_file(prev_day)
        if prev_file:
            prev_text = prev_file.read_text(errors="replace")
            prev_msgs = extract_messages(prev_text, window_size, from_end=True)
            if prev_msgs:
                parts.append(f"[Context: end of {prev_day.strftime('%Y-%m-%d')}]\n{prev_msgs}")

        # Current day (full)
        parts.append(document)

        # Next day: first N messages
        next_file = find_day_file(next_day)
        if next_file:
            next_text = next_file.read_text(errors="replace")
            next_msgs = extract_messages(next_text, window_size, from_end=False)
            if next_msgs:
                parts.append(f"[Context: start of {next_day.strftime('%Y-%m-%d')}]\n{next_msgs}")

        return "\n\n---\n\n".join(parts)

    def _ensure_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(
                api_key=self.api_key,
                timeout=120.0,  # 2 min per request -- prevents hung connections
            )

    @staticmethod
    def _split_into_segments(document: str, gap_minutes: int) -> list[str]:
        """Split a document into conversation segments based on time gaps.

        Parses timestamp patterns in messages (e.g., "**Name** (HH:MM AM):")
        and splits when the gap between consecutive messages exceeds gap_minutes.

        Returns a list of segment strings. If no timestamps are found or only
        one segment exists, returns [document].
        """
        import re
        from datetime import datetime, timedelta

        lines = document.split("\n")

        # Match common timestamp patterns in iMessage/Teams:
        #   **Name** (7:44 PM):    or    **Name** (2026-03-09 7:44 PM):
        #   Also: <!-- idhash: ... --> lines before messages
        time_pattern = re.compile(
            r'\*\*[^*]+\*\*\s*\((?:[\d/]+ )?(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))\)'
        )
        # Also match ISO timestamps from frontmatter: date: 2026-03-30T14:53:12
        iso_pattern = re.compile(r'date:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})')

        # Build list of (line_index, datetime) for lines with timestamps
        timed_lines = []
        for i, line in enumerate(lines):
            m = time_pattern.search(line)
            if m:
                try:
                    t = datetime.strptime(m.group(1).strip(), "%I:%M %p")
                    timed_lines.append((i, t))
                except ValueError:
                    pass
                continue
            m = iso_pattern.search(line)
            if m:
                try:
                    t = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M")
                    timed_lines.append((i, t))
                except ValueError:
                    pass

        if len(timed_lines) < 2:
            return [document]

        # Find split points where gap exceeds threshold
        gap = timedelta(minutes=gap_minutes)
        split_lines = []  # line indices where new segments start

        for j in range(1, len(timed_lines)):
            prev_time = timed_lines[j - 1][1]
            curr_time = timed_lines[j][1]
            # Handle day wrapping (AM times after PM times)
            diff = curr_time - prev_time
            if diff.total_seconds() < 0:
                diff += timedelta(days=1)
            if diff >= gap:
                split_lines.append(timed_lines[j][0])

        if not split_lines:
            return [document]

        # Build segments
        segments = []
        prev = 0
        for sl in split_lines:
            # Walk back to include any comment/blank lines before the message
            start = sl
            while start > prev and (not lines[start - 1].strip() or
                                     lines[start - 1].strip().startswith("<!--")):
                start -= 1
            segment_text = "\n".join(lines[prev:start]).strip()
            if segment_text:
                segments.append(segment_text)
            prev = start

        # Final segment
        final = "\n".join(lines[prev:]).strip()
        if final:
            segments.append(final)

        return segments if segments else [document]

    @staticmethod
    def _find_chunk_segment(segments: list[str], chunk_text: str) -> str:
        """Find which segment contains the chunk text (or most overlap).

        Returns the matching segment, or the full concatenation if no match.
        """
        # Exact substring match first
        for seg in segments:
            if chunk_text[:200] in seg:
                return seg

        # Fallback: find segment with most word overlap
        chunk_words = set(chunk_text.split()[:50])
        best_seg = segments[0]
        best_score = 0
        for seg in segments:
            seg_words = set(seg.split()[:200])
            score = len(chunk_words & seg_words)
            if score > best_score:
                best_score = score
                best_seg = seg
        return best_seg

    def contextualize_chunks(self, document: str, chunk_texts: list[str],
                             source: str = None, file_path=None) -> list[str]:
        """Generate context prefix for each chunk.

        Uses prompt caching: the document is sent as a cached system message
        so it's only billed once per document. Each chunk is a separate user
        turn that triggers a cache read on the document.

        For sources in CONTEXT_SEGMENT_SOURCES, the document is split into
        conversation segments and each chunk gets context from its own segment
        rather than the entire file. This produces more focused context for
        daily roll-up files (iMessage, Teams).

        Args:
            document: Full document text
            chunk_texts: List of chunk texts
            source: Source type (e.g. "fireflies", "limitless") for per-source thresholds
            file_path: Path to the source file (for sliding window assembly)

        Returns:
            List of context strings (one per chunk). Empty string if generation fails.
        """
        if not self.enabled:
            return [""] * len(chunk_texts)

        # Per-source threshold (0 = context everything for this source)
        threshold = CONTEXT_SOURCE_THRESHOLDS.get(source, CONTEXT_MIN_DOC_TOKENS)

        # Skip documents below threshold
        if threshold > 0 and len(document) < threshold * CHARS_PER_TOKEN:
            return [""] * len(chunk_texts)

        # Sliding window: for sources like teams-daily, load adjacent day files
        window_size = CONTEXT_SLIDING_WINDOW.get(source)
        if window_size and file_path:
            document = self._build_sliding_window(document, file_path, window_size)

        # Conversation-segment context: split document into segments and use
        # the relevant segment as context for each chunk (instead of full file).
        segments = None
        gap_minutes = CONTEXT_SEGMENT_SOURCES.get(source)
        if gap_minutes:
            segments = self._split_into_segments(document, gap_minutes)
            if len(segments) > 1:
                print(f"  Segment context: {len(segments)} segments for {source}",
                      file=sys.stderr)

        # Guard: truncate document if it exceeds Haiku's context window (~200K tokens)
        # Leave room for the chunk + prompt (~1K tokens)
        MAX_DOC_CHARS = 180_000 * CHARS_PER_TOKEN  # ~720K chars = ~180K tokens
        if len(document) > MAX_DOC_CHARS:
            document = document[:MAX_DOC_CHARS]

        self._ensure_client()
        contexts = []

        for chunk_text in chunk_texts:
            # Use segment-level context if available
            if segments and len(segments) > 1:
                ctx_doc = self._find_chunk_segment(segments, chunk_text)
                # Truncate segment if needed
                if len(ctx_doc) > MAX_DOC_CHARS:
                    ctx_doc = ctx_doc[:MAX_DOC_CHARS]
            else:
                ctx_doc = document

            ctx = self._generate_one(ctx_doc, chunk_text)
            contexts.append(ctx)

        return contexts

    def _generate_one(self, document: str, chunk_text: str) -> str:
        """Generate context for a single chunk with retry.

        The document goes in a cached system message so multiple chunks
        from the same document reuse the cached input tokens. Only the
        chunk text (user message) changes per call.

        Rate limits are NOT errors -- they're flow control. We wait and
        retry indefinitely on rate limits. Real errors get limited retries.
        """
        error_retries = 0
        rate_limit_hits = 0

        while True:
            try:
                response = self._client.messages.create(
                    model=ANTHROPIC_MODEL,
                    max_tokens=200,
                    system=[
                        {
                            "type": "text",
                            "text": f"<document>\n{document}\n</document>",
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[
                        {
                            "role": "user",
                            "content": (
                                "Here is the chunk we want to situate within "
                                "the whole document:\n"
                                f"<chunk>\n{chunk_text}\n</chunk>\n"
                                "Please give a short succinct context to situate "
                                "this chunk within the overall document for the "
                                "purposes of improving search retrieval of the "
                                "chunk. Answer only with the succinct context "
                                "and nothing else."
                            ),
                        }
                    ],
                )
                return response.content[0].text.strip()

            except Exception as e:
                error_str = str(e)

                if "rate_limit" in error_str.lower() or "429" in error_str:
                    # Rate limits: wait and retry forever. These are flow control.
                    rate_limit_hits += 1
                    if rate_limit_hits <= 3:
                        wait = 60
                    else:
                        wait = 300  # After 3 consecutive, wait 5 min
                    print(f"  Rate limit #{rate_limit_hits}, waiting {wait}s",
                          file=sys.stderr)
                    time.sleep(wait)
                    continue  # Never count against error retries

                elif "overloaded" in error_str.lower() or "529" in error_str:
                    # Server overloaded: similar to rate limit, wait and retry
                    wait = 120
                    print(f"  Anthropic overloaded, waiting {wait}s", file=sys.stderr)
                    time.sleep(wait)
                    continue

                else:
                    # Real error: limited retries
                    error_retries += 1
                    if error_retries < ANTHROPIC_RETRIES:
                        wait = 2 ** error_retries
                        print(f"  Anthropic error {error_retries}/{ANTHROPIC_RETRIES}: {e}",
                              file=sys.stderr)
                        time.sleep(wait)
                    else:
                        print(f"  WARNING: Context generation failed, skipping: {e}",
                              file=sys.stderr)
                        return ""
