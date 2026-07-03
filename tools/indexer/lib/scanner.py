"""File discovery and incremental state tracking."""

import fcntl
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from fnmatch import fnmatch

from .config import (DATA_DIR, MEMORY_DIR, MEMORY_KEY_PREFIX,
                     MEMORY_EXCLUDE_DIRS, STATE_FILE, EMBEDDING_MODEL,
                     EMBEDDING_DIM, DOCUMENTS_INCLUDE_PREFIXES,
                     EXCLUDE_FILENAME_PATTERNS)


def _file_hash(path: Path) -> str:
    """MD5 hash of file content."""
    return hashlib.md5(path.read_bytes()).hexdigest()


# -- Session-slice subset dedup (RAG audit 2026-07-02) ------------------------
# The session slicer emits 10-minute windows sliding every 5 minutes, so many
# slice files are strict time-range subsets of a sibling (e.g. 0809-0811.md
# inside 0809-0816.md). Indexing both floods retrieval with duplicates. We
# exclude verified subsets AT INDEX TIME (files stay on disk -- other
# consumers read the fine slices).
#
# A slice is skipped only when ALL THREE hold, in the same day directory:
#   1. its filename [start,end] range is contained in another slice's range
#      (HHMM-HHMM parsed from the filename; end < start = midnight cross),
#   2. both slices carry the same session_id (day dirs mix concurrent
#      sessions -- a time-contained slice from another session is NOT a
#      duplicate), and
#   3. its message blocks are a verified subset of the container's (the
#      incremental slicer can emit a nominally-wider window that misses
#      earlier messages -- filename containment alone loses content).
# Identical ranges (possible across subagent prefixes) keep the
# lexicographically-first filename.

SLICE_SUBSET_DIRS = ("sessions/slices", "sessions/subagent-slices")
_SLICE_NAME_RE = re.compile(r"(\d{4})-(\d{4})\.md$")
_SLICE_SESSION_RE = re.compile(r"^session_id:\s*(\S+)", re.MULTILINE)
_SLICE_MSG_SPLIT_RE = re.compile(r"\n(?=\*\*[^*\n]+\*\* \(\d\d:\d\d\):)")


def _slice_range(name: str) -> tuple[int, int] | None:
    """Parse trailing HHMM-HHMM from a slice filename into minutes.
    End < start means the slice crosses midnight (+24h)."""
    m = _SLICE_NAME_RE.search(name)
    if not m:
        return None
    s, e = int(m.group(1)), int(m.group(2))
    s = (s // 100) * 60 + s % 100
    e = (e // 100) * 60 + e % 100
    if e < s:
        e += 1440
    return (s, e)


def _slice_messages(text: str) -> set[str]:
    """Message blocks of a slice file (frontmatter stripped), as a set."""
    body = text.split("---", 2)[-1]
    return {b.strip() for b in _SLICE_MSG_SPLIT_RE.split(body)
            if b.strip().startswith("**")}


def compute_subset_slices(data_dir: Path = DATA_DIR) -> set[Path]:
    """Slice files to exclude from indexing: verified content-subsets of a
    same-session sibling in the same day directory. Deterministic."""
    excluded: set[Path] = set()
    for rel_root in SLICE_SUBSET_DIRS:
        root = data_dir / rel_root
        if not root.is_dir():
            continue
        for day_dir in sorted(root.iterdir()):
            if not day_dir.is_dir():
                continue
            # Group parseable slices by session_id
            groups: dict[str, list[tuple[Path, tuple[int, int], str]]] = {}
            for f in sorted(day_dir.glob("*.md")):
                rng = _slice_range(f.name)
                if rng is None:
                    continue
                try:
                    text = f.read_text(errors="replace")
                except OSError:
                    continue
                m = _SLICE_SESSION_RE.search(text[:500])
                if not m:
                    continue
                groups.setdefault(m.group(1), []).append((f, rng, text))

            for entries in groups.values():
                if len(entries) < 2:
                    continue
                msg_cache: dict[Path, set[str]] = {}

                def msgs(path: Path, text: str) -> set[str]:
                    if path not in msg_cache:
                        msg_cache[path] = _slice_messages(text)
                    return msg_cache[path]

                for f, (s, e), text in entries:
                    for of, (os_, oe), otext in entries:
                        if of == f:
                            continue
                        if not (os_ <= s and e <= oe):
                            continue
                        if (os_, oe) == (s, e) and not (of.name < f.name):
                            continue  # identical range: keep lex-first
                        # Verify actual content containment
                        if msgs(f, text) <= msgs(of, otext):
                            excluded.add(f)
                            break
    return excluded


def path_to_key(path: Path, data_dir: Path = DATA_DIR) -> str:
    """State-file key for a path. Memory-root keys are prefixed so they
    can never collide with data/-relative keys."""
    try:
        return MEMORY_KEY_PREFIX + str(path.relative_to(MEMORY_DIR))
    except ValueError:
        return str(path.relative_to(data_dir))


def key_to_path(key: str, data_dir: Path = DATA_DIR) -> Path:
    """Inverse of path_to_key."""
    if key.startswith(MEMORY_KEY_PREFIX):
        return MEMORY_DIR / key[len(MEMORY_KEY_PREFIX):]
    return data_dir / key


class FileScanner:
    """Discovers changed/new/deleted files and tracks indexing state."""

    def __init__(self, state_file: Path = STATE_FILE, data_dir: Path = DATA_DIR):
        self.state_file = state_file
        self.data_dir = data_dir
        self.state = self._load_state()
        # Keys this process actually modified/deleted. save() only asserts
        # precedence for these, so a long-running sync can no longer clobber
        # concurrent state edits (other source-scoped runs, reconcile_context
        # resets) with the stale full snapshot it loaded at startup.
        self._dirty_keys: set[str] = set()
        self._deleted_keys: set[str] = set()

    def _load_state(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except (json.JSONDecodeError, OSError):
                print("WARNING: state file corrupted, starting fresh", file=sys.stderr)
        return {
            "version": 1,
            "last_run": None,
            "embedding_model": EMBEDDING_MODEL,
            "embedding_dim": EMBEDDING_DIM,
            "files": {},
        }

    def check_model_change(self) -> bool:
        """Returns True if embedding model/dim changed since last run."""
        return (
            self.state.get("embedding_model") != EMBEDDING_MODEL
            or self.state.get("embedding_dim") != EMBEDDING_DIM
        )

    def _source_key(self, path: Path) -> str:
        """Source key for round-robin grouping: connector/source (first two
        path components under data/), e.g. 'google/mail', 'o365/teams-daily'.
        The whole memory/ root is one group."""
        try:
            path.relative_to(MEMORY_DIR)
            return "@memory"
        except ValueError:
            pass
        try:
            parts = path.relative_to(self.data_dir).parts
        except ValueError:
            parts = path.parts
        dirs = parts[:-1]  # directory components only (drop filename)
        return "/".join(dirs[:2]) if dirs else "_root"

    def _round_robin(self, files: list[Path]) -> list[Path]:
        """Interleave the queue per source so one source's backlog cannot
        starve the rest. Within a source, original (chronological path) order
        is preserved. Replaces plain alphabetical processing, where e.g. a
        google/mail backlog sat in front of every later-alphabet source.
        """
        groups: dict[str, list[Path]] = {}
        for f in files:
            groups.setdefault(self._source_key(f), []).append(f)

        ordered: list[Path] = []
        queues = [groups[k] for k in sorted(groups)]
        while queues:
            still_pending = []
            for q in queues:
                ordered.append(q.pop(0))
                if q:
                    still_pending.append(q)
            queues = still_pending
        return ordered

    def scan(self, force: bool = False, source_filter: str | None = None) -> tuple[list[Path], list[str]]:
        """Scan data dir for changes.

        Returns:
            (files_to_index, file_keys_to_delete)
        """
        to_index = []
        on_disk = set()

        # Session-slice subset dedup (see compute_subset_slices docstring).
        # Computed once per scan; excluded files fall out of on_disk, so
        # already-indexed subsets surface in to_delete.
        subset_slices = compute_subset_slices(self.data_dir)
        self.subset_slices_skipped = len(subset_slices)
        if subset_slices:
            print(f"  Slice dedup: {len(subset_slices)} subset slice files "
                  f"excluded from indexing", file=sys.stderr)

        for md_file in sorted(self.data_dir.rglob("*.md")):
            if md_file.name.startswith("."):
                continue

            # Filename pattern exclusions
            if any(fnmatch(md_file.name, pat) for pat in EXCLUDE_FILENAME_PATTERNS):
                continue

            # Source-level exclusions
            try:
                rel_str = str(md_file.relative_to(self.data_dir))
            except ValueError:
                continue

            # Photos: low-value metadata (UUIDs + GPS), skip entirely
            if rel_str.startswith("photos/"):
                continue

            # iMessage per-contact rolling files duplicate imessage/daily/
            # (RAG audit 2026-07-02: same messages indexed twice). Keep
            # daily/ -- better context pipeline (sliding window + segments).
            # The conversations/ files stay on disk for skills that read
            # them directly; they just aren't embedded.
            if rel_str.startswith("imessage/conversations/"):
                continue

            # Session-slice subset dedup (verified duplicates only)
            if md_file in subset_slices:
                continue

            # Documents: whitelist only valuable paths
            if rel_str.startswith("documents/") and not any(
                rel_str.startswith(prefix) for prefix in DOCUMENTS_INCLUDE_PREFIXES
            ):
                continue

            # Source filter
            if source_filter:
                try:
                    rel = md_file.relative_to(self.data_dir)
                    parts = rel.parts
                    if not any(source_filter in p for p in parts[:2]):
                        continue
                except ValueError:
                    continue

            key = str(md_file.relative_to(self.data_dir))
            on_disk.add(key)

            if force:
                to_index.append(md_file)
                continue

            h = _file_hash(md_file)
            stored = self.state["files"].get(key)
            if stored is None or stored.get("hash") != h:
                to_index.append(md_file)

        # Second root: memory/ layer (source "memory", keys prefixed).
        # Excludes memory/archive/. NOT the briefing-book vault (iCloud TCC).
        if MEMORY_DIR.is_dir():
            for md_file in sorted(MEMORY_DIR.rglob("*.md")):
                if md_file.name.startswith("."):
                    continue
                rel = md_file.relative_to(MEMORY_DIR)
                if rel.parts and rel.parts[0] in MEMORY_EXCLUDE_DIRS:
                    continue
                if any(fnmatch(md_file.name, pat)
                       for pat in EXCLUDE_FILENAME_PATTERNS):
                    continue
                if source_filter and source_filter not in "memory":
                    continue

                key = path_to_key(md_file, self.data_dir)
                on_disk.add(key)

                if force:
                    to_index.append(md_file)
                    continue

                h = _file_hash(md_file)
                stored = self.state["files"].get(key)
                if stored is None or stored.get("hash") != h:
                    to_index.append(md_file)

        # Deleted files
        to_delete = []
        for key in list(self.state["files"].keys()):
            if source_filter:
                if not any(source_filter in p for p in key.split("/")[:2]):
                    continue
            if key not in on_disk:
                to_delete.append(key)

        # Per-source round-robin so no single source's backlog starves others
        to_index = self._round_robin(to_index)

        return to_index, to_delete

    def update_file(self, file_path: Path, chunk_count: int, context_done: bool = False):
        """Mark a file as indexed.

        Args:
            file_path: Path to the indexed file
            chunk_count: Number of chunks produced
            context_done: Whether the chunks NOW IN THE INDEX carry Haiku
                          context (or skipped it intentionally: below
                          threshold, bulk mail, oversized doc).

        The flag records exactly what this run did. Indexing a file always
        replaces its Qdrant points, so any previously generated context is
        gone -- the old "never downgrades" OR with the prior flag lied about
        index reality and permanently hid re-indexed files (whose context had
        just been wiped) from --backfill-context. That divergence is the
        root cause of the 2026-07-02 context-coverage audit finding (F3b).
        """
        key = path_to_key(file_path, self.data_dir)
        self.state["files"][key] = {
            "hash": _file_hash(file_path),
            "chunks": chunk_count,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "context_done": context_done,
        }
        self._dirty_keys.add(key)

    def set_context_pending(self, key: str) -> bool:
        """Flip context_done to False for a tracked file (reconciliation).

        Returns True if the flag was actually flipped, False if the key is
        untracked or already pending. Marks the entry dirty so save() asserts
        it over the on-disk copy.
        """
        entry = self.state["files"].get(key)
        if not entry or not entry.get("context_done", False):
            return False
        entry["context_done"] = False
        self._dirty_keys.add(key)
        return True

    def needs_context(self, file_path: Path) -> bool:
        """Check if a file needs contextual retrieval (not yet done)."""
        key = path_to_key(file_path, self.data_dir)
        stored = self.state["files"].get(key)
        if stored is None:
            return True
        return not stored.get("context_done", False)

    def remove_file(self, key: str):
        """Remove a file from state."""
        self.state["files"].pop(key, None)
        # Track deletion so save() can propagate it across the merge
        self._deleted_keys.add(key)
        self._dirty_keys.discard(key)

    def save(self):
        """Atomic write state to disk with file-level lock for concurrency safety."""
        # Re-read current state and merge our file entries to avoid
        # clobbering updates from a concurrent source-specific indexer run.
        lock_path = self.state_file.with_suffix(".state-lock")
        with open(lock_path, "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                # Reload latest state from disk
                if self.state_file.exists():
                    try:
                        disk_state = json.loads(self.state_file.read_text())
                    except (json.JSONDecodeError, OSError):
                        disk_state = {}
                else:
                    disk_state = {}

                # Merge: only entries THIS process modified take precedence.
                # The old full-dict update() asserted our (possibly hours-
                # stale) startup snapshot over every key, silently reverting
                # anything another process wrote in the meantime.
                merged_files = disk_state.get("files", {})
                own_files = self.state.get("files", {})
                for key in self._dirty_keys:
                    if key in own_files:
                        merged_files[key] = own_files[key]

                # Propagate explicit deletions from this session.
                # remove_file() tracks each key it removes; we need to delete
                # those from the disk-merged dict too, otherwise the merge
                # would resurrect them from disk_state on every save.
                for key in self._deleted_keys:
                    merged_files.pop(key, None)

                out = {
                    "files": merged_files,
                    "last_run": datetime.now(timezone.utc).isoformat(),
                    "embedding_model": EMBEDDING_MODEL,
                    "embedding_dim": EMBEDDING_DIM,
                }

                tmp = self.state_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(out, indent=2))
                tmp.rename(self.state_file)

                # Update in-memory state to match what we wrote, and clear
                # the dirty/deleted sets -- those edits are now persisted.
                self.state = out
                self._dirty_keys = set()
                self._deleted_keys = set()
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def stats(self) -> dict:
        """Return summary stats."""
        files = self.state.get("files", {})
        total_chunks = sum(f.get("chunks", 0) for f in files.values())
        return {
            "files_tracked": len(files),
            "total_chunks": total_chunks,
            "last_run": self.state.get("last_run"),
            "embedding_model": self.state.get("embedding_model"),
            "embedding_dim": self.state.get("embedding_dim"),
        }
