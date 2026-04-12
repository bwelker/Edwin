"""File discovery and incremental state tracking."""

import fcntl
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from fnmatch import fnmatch

from .config import (DATA_DIR, STATE_FILE, EMBEDDING_MODEL, EMBEDDING_DIM,
                     DOCUMENTS_INCLUDE_PREFIXES, EXCLUDE_FILENAME_PATTERNS)


def _file_hash(path: Path) -> str:
    """MD5 hash of file content."""
    return hashlib.md5(path.read_bytes()).hexdigest()


class FileScanner:
    """Discovers changed/new/deleted files and tracks indexing state."""

    def __init__(self, state_file: Path = STATE_FILE, data_dir: Path = DATA_DIR):
        self.state_file = state_file
        self.data_dir = data_dir
        self.state = self._load_state()

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

    def scan(self, force: bool = False, source_filter: str | None = None) -> tuple[list[Path], list[str]]:
        """Scan data dir for changes.

        Returns:
            (files_to_index, file_keys_to_delete)
        """
        to_index = []
        on_disk = set()

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

        # Deleted files
        to_delete = []
        for key in list(self.state["files"].keys()):
            if source_filter:
                if not any(source_filter in p for p in key.split("/")[:2]):
                    continue
            if key not in on_disk:
                to_delete.append(key)

        return to_index, to_delete

    def update_file(self, file_path: Path, chunk_count: int, context_done: bool = False):
        """Mark a file as indexed.

        Args:
            file_path: Path to the indexed file
            chunk_count: Number of chunks produced
            context_done: Whether Haiku contextual retrieval was run for this file.
                          Never downgrades: if context was previously done and this
                          run skipped it, the flag stays True.
        """
        key = str(file_path.relative_to(self.data_dir))
        # Preserve existing context_done if this run didn't do context
        existing = self.state["files"].get(key, {})
        was_done = existing.get("context_done", False)

        self.state["files"][key] = {
            "hash": _file_hash(file_path),
            "chunks": chunk_count,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "context_done": context_done or was_done,
        }

    def needs_context(self, file_path: Path) -> bool:
        """Check if a file needs contextual retrieval (not yet done)."""
        key = str(file_path.relative_to(self.data_dir))
        stored = self.state["files"].get(key)
        if stored is None:
            return True
        return not stored.get("context_done", False)

    def remove_file(self, key: str):
        """Remove a file from state."""
        self.state["files"].pop(key, None)
        # Track deletion so save() can propagate it across the merge
        if not hasattr(self, "_deleted_keys"):
            self._deleted_keys = set()
        self._deleted_keys.add(key)

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

                # Merge: our in-memory file entries take precedence
                merged_files = disk_state.get("files", {})
                merged_files.update(self.state.get("files", {}))

                # Propagate explicit deletions from this session.
                # remove_file() tracks each key it removes; we need to delete
                # those from the disk-merged dict too, otherwise the merge
                # would resurrect them from disk_state on every save.
                for key in getattr(self, "_deleted_keys", set()):
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

                # Update in-memory state to match what we wrote
                self.state = out
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
