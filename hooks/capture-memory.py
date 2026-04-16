#!/usr/bin/env python3
"""Edwin PreCompact hook -- capture memorable content before auto-compaction.

When Claude Code's auto-compaction fires, volatile working memory is condensed
and pieces vanish. This hook scrapes the transcript for NOTEs, commitments,
and date-bearing references, writes them to an overnight log, and upserts to
the configured vector backend for later recall.

Heuristics only -- no LLM calls, must stay fast. A scheduled job can do
LLM-assisted extraction later over the raw material dropped here.

Backend is swappable. See inject-memory.py for the protocol. This hook only
needs a backend that can embed + upsert.

Configure via ~/.edwin/hooks.json. Logs to ~/.edwin/logs/hooks/capture-memory.log.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "backend": "qdrant_ollama",
    "ollama_url": "http://localhost:11434",
    "embedding_model": "qwen3-embedding:8b",
    "embedding_dim": 2048,
    "qdrant_url": "http://localhost:6333",
    "collection": "edwin-memory",
    "embed_timeout": 10.0,
    "upsert_timeout": 5.0,
    "max_captures": 40,
    "max_transcript_bytes": 2_000_000,
    "captured_dir": str(Path.home() / ".edwin" / "memory" / "captured"),
    "memory_index": "",
}

CONFIG_PATH = Path(os.environ.get(
    "EDWIN_HOOKS_CONFIG",
    str(Path.home() / ".edwin" / "hooks.json"),
))
LOG_PATH = Path.home() / ".edwin" / "logs" / "hooks" / "capture-memory.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text()))
        except Exception:
            pass
    env_map = {
        "EDWIN_BACKEND": "backend",
        "OLLAMA_URL": "ollama_url",
        "EMBEDDING_MODEL": "embedding_model",
        "QDRANT_URL": "qdrant_url",
        "EDWIN_COLLECTION": "collection",
    }
    for env, key in env_map.items():
        if env in os.environ:
            cfg[key] = os.environ[env]
    return cfg


def log(msg: str) -> None:
    try:
        ts = datetime.now().isoformat(timespec="seconds")
        with LOG_PATH.open("a") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Backend protocol + default implementation
# ---------------------------------------------------------------------------

class CaptureBackend(Protocol):
    def embed(self, text: str) -> list[float] | None: ...
    def upsert(self, records: list[dict]) -> bool: ...


class QdrantOllamaCaptureBackend:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.ollama_url = cfg["ollama_url"]
        self.qdrant_url = cfg["qdrant_url"]
        self.model = cfg["embedding_model"]
        self.dim = int(cfg["embedding_dim"])
        self.collection = cfg["collection"]
        self.embed_timeout = float(cfg["embed_timeout"])
        self.upsert_timeout = float(cfg["upsert_timeout"])

    def embed(self, text: str) -> list[float] | None:
        payload = json.dumps({
            "model": self.model,
            "input": text,
            "truncate": True,
        }).encode()
        try:
            req = urllib.request.Request(
                f"{self.ollama_url}/api/embed",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.embed_timeout) as resp:
                raw = resp.read().decode()
                raw = raw.replace("NaN", "0.0").replace("Infinity", "0.0").replace("-Infinity", "0.0")
                data = json.loads(raw)
                embeddings = data.get("embeddings", [])
                if not embeddings:
                    return None
                vec = embeddings[0]
                if len(vec) > self.dim:
                    vec = vec[:self.dim]
                return vec
        except Exception as e:
            log(f"embed error: {e}")
            return None

    def upsert(self, records: list[dict]) -> bool:
        """Each record: {id, vector, payload}. Vector must be dense list[float]."""
        if not records:
            return True
        # Match Edwin's named-vector schema ("text-dense"). Backends that use
        # a simpler unnamed schema should flatten in their own subclass.
        points = [
            {
                "id": r["id"],
                "vector": {"text-dense": r["vector"]},
                "payload": r["payload"],
            }
            for r in records
        ]
        try:
            req = urllib.request.Request(
                f"{self.qdrant_url}/collections/{self.collection}/points?wait=false",
                data=json.dumps({"points": points}).encode(),
                headers={"Content-Type": "application/json"},
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=self.upsert_timeout) as resp:
                body = resp.read().decode()
                return '"status":"ok"' in body or '"status": "ok"' in body
        except Exception as e:
            log(f"qdrant upsert error: {e}")
            return False


def load_backend(cfg: dict[str, Any]) -> CaptureBackend:
    spec = cfg.get("backend", "qdrant_ollama")
    if spec == "qdrant_ollama":
        return QdrantOllamaCaptureBackend(cfg)
    if ":" in spec:
        module_path, cls_name = spec.split(":", 1)
        mod = importlib.import_module(module_path)
        cls = getattr(mod, cls_name)
        return cls(cfg)
    raise ValueError(f"unknown backend: {spec}")


# ---------------------------------------------------------------------------
# Heuristic extraction
# ---------------------------------------------------------------------------

NOTE_PREFIX = re.compile(r"^\s*(?:-\s*)?NOTE:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

COMMITMENT_PATTERNS = [
    re.compile(r"\bI['’]ll\s+(\w[\w\s,'’-]{5,120})", re.IGNORECASE),
    re.compile(r"\bWe['’]ll\s+(\w[\w\s,'’-]{5,120})", re.IGNORECASE),
    re.compile(r"\bremind me to\s+(\w[\w\s,'’-]{3,120})", re.IGNORECASE),
    re.compile(r"\blet['’]s\s+(\w[\w\s,'’-]{5,120})", re.IGNORECASE),
    re.compile(r"\bI['’]m going to\s+(\w[\w\s,'’-]{5,120})", re.IGNORECASE),
    re.compile(r"\bpromised to\s+(\w[\w\s,'’-]{5,120})", re.IGNORECASE),
    re.compile(r"\bwill send\s+(\w[\w\s,'’-]{3,120})", re.IGNORECASE),
    re.compile(r"\bdeadline (?:is|of)\s+(\w[\w\s,'’-]{3,120})", re.IGNORECASE),
]

DATE_NEAR = re.compile(
    r"\b(?:by|on|before|after|due)\s+"
    r"(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day|"
    r"\b\d{4}-\d{2}-\d{2}\b|"
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\b",
    re.IGNORECASE,
)

INJECTION_PATTERNS = [
    re.compile(r"</?system[^>]*>", re.IGNORECASE),
    re.compile(r"\[INST\]|\[/INST\]", re.IGNORECASE),
    re.compile(r"<\|im_start\|>|<\|im_end\|>", re.IGNORECASE),
    re.compile(r"<\|endoftext\|>", re.IGNORECASE),
    re.compile(r"</?assistant[^>]*>", re.IGNORECASE),
    re.compile(r"</?user[^>]*>", re.IGNORECASE),
    re.compile(r"</?relevant-memories[^>]*>", re.IGNORECASE),
]

SKIP_MARKERS = [
    "<relevant-memories>",
    "<system-reminder>",
    "hookSpecificOutput",
    "<function_calls>",
    "<command-name>",
]


def sanitize(text: str) -> str:
    for pat in INJECTION_PATTERNS:
        text = pat.sub("", text)
    return text.strip()


def should_skip(text: str) -> bool:
    if not text or len(text) < 10 or len(text) > 4000:
        return True
    for marker in SKIP_MARKERS:
        if marker in text:
            return True
    if text.lstrip().startswith("<") and "</" in text:
        return True
    return False


def load_transcript(path: str | None, max_bytes: int) -> list[dict]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    try:
        size = p.stat().st_size
        if size > max_bytes:
            with p.open("rb") as f:
                head = f.read(max_bytes // 2).decode("utf-8", errors="ignore")
                f.seek(-max_bytes // 2, os.SEEK_END)
                tail = f.read().decode("utf-8", errors="ignore")
            content = head + "\n" + tail
        else:
            content = p.read_text(errors="ignore")
    except Exception as e:
        log(f"transcript read error: {e}")
        return []

    messages: list[dict] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            messages.append(json.loads(line))
        except Exception:
            continue
    return messages


def extract_text_blocks(messages: list[dict]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for msg in messages:
        record = msg.get("message") if isinstance(msg.get("message"), dict) else msg
        role = record.get("role") or msg.get("role") or ""
        content = record.get("content")
        if isinstance(content, str):
            out.append((role, content))
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = block.get("text")
                    if isinstance(t, str):
                        out.append((role, t))
    return out


def extract_captures(blocks: list[tuple[str, str]], max_captures: int) -> list[dict]:
    seen: set[str] = set()
    captures: list[dict] = []

    for role, text in blocks:
        if should_skip(text):
            continue
        clean = sanitize(text)
        if not clean:
            continue

        for m in NOTE_PREFIX.finditer(clean):
            note = m.group(1).strip().rstrip(".")
            if len(note) < 5:
                continue
            key = hashlib.sha256(note.lower().encode()).hexdigest()[:16]
            if key in seen:
                continue
            seen.add(key)
            captures.append({"text": note, "kind": "note", "role": role, "key": key})
            if len(captures) >= max_captures:
                return captures

        if role == "user":
            for pat in COMMITMENT_PATTERNS:
                for m in pat.finditer(clean):
                    phrase = m.group(0).strip().rstrip(".")
                    phrase = phrase.split(".")[0].split("\n")[0][:200]
                    if len(phrase) < 8:
                        continue
                    key = hashlib.sha256(phrase.lower().encode()).hexdigest()[:16]
                    if key in seen:
                        continue
                    seen.add(key)
                    captures.append({"text": phrase, "kind": "commitment", "role": role, "key": key})
                    if len(captures) >= max_captures:
                        return captures

        if DATE_NEAR.search(clean):
            for sentence in re.split(r"(?<=[.!?])\s+", clean):
                if len(sentence) < 15 or len(sentence) > 300:
                    continue
                if not DATE_NEAR.search(sentence):
                    continue
                tokens = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", sentence)
                if not any(t not in {"The", "This", "That", "When", "Where", "With"} for t in tokens):
                    continue
                key = hashlib.sha256(sentence.lower().encode()).hexdigest()[:16]
                if key in seen:
                    continue
                seen.add(key)
                captures.append({"text": sentence.strip(), "kind": "deadline", "role": role, "key": key})
                if len(captures) >= max_captures:
                    return captures

    return captures


def dedup_against_memory_index(captures: list[dict], index_path: Path | None) -> list[dict]:
    if not index_path or not index_path.exists() or not captures:
        return captures
    try:
        idx = index_path.read_text(errors="ignore").lower()
    except Exception:
        return captures
    out = []
    for c in captures:
        needle = c["text"].lower()[:40]
        if len(needle) >= 20 and needle in idx:
            continue
        out.append(c)
    return out


def write_captured_log(captures: list[dict], session_id: str, captured_dir: Path) -> Path:
    captured_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    sid = (session_id or "unknown")[:12]
    path = captured_dir / f"{today}-{sid}.md"
    ts = datetime.now().isoformat(timespec="seconds")
    header_needed = not path.exists()
    with path.open("a") as f:
        if header_needed:
            f.write(f"# Captured memory -- session {sid}\n\n")
            f.write(f"Automatically captured by PreCompact hook. Raw heuristics only -- "
                    f"review before promoting to curated memory.\n\n")
        f.write(f"## {ts}\n\n")
        for c in captures:
            kind = c["kind"].upper()
            f.write(f"- NOTE: [{kind}] {c['text']}\n")
        f.write("\n")
    return path


def main() -> int:
    start = time.monotonic()
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
    except Exception as e:
        log(f"stdin parse error: {e}")
        return 0

    session_id = payload.get("session_id") or ""
    transcript_path = payload.get("transcript_path")
    trigger = payload.get("trigger") or payload.get("matcher") or "auto"
    sid = session_id[:12]

    cfg = load_config()

    log(f"[{sid}] precompact trigger={trigger} transcript={transcript_path}")

    messages = load_transcript(transcript_path, int(cfg["max_transcript_bytes"]))
    if not messages:
        log(f"[{sid}] no messages, skipping")
        return 0

    blocks = extract_text_blocks(messages)
    captures = extract_captures(blocks, int(cfg["max_captures"]))

    mi = cfg.get("memory_index")
    if mi:
        captures = dedup_against_memory_index(captures, Path(mi).expanduser())

    if not captures:
        elapsed = (time.monotonic() - start) * 1000
        log(f"[{sid}] no captures ({elapsed:.0f}ms)")
        return 0

    captured_dir = Path(cfg["captured_dir"]).expanduser()
    log_file = write_captured_log(captures, session_id, captured_dir)

    try:
        backend = load_backend(cfg)
    except Exception as e:
        log(f"backend init failed: {e} (captures still saved to disk)")
        return 0

    records: list[dict] = []
    today = datetime.now().strftime("%Y-%m-%d")
    for c in captures:
        vec = backend.embed(c["text"])
        if vec is None:
            continue
        records.append({
            "id": str(uuid.uuid4()),
            "vector": vec,
            "payload": {
                "text": c["text"],
                "source": "captured",
                "kind": c["kind"],
                "role": c["role"],
                "date": today,
                "session_id": session_id,
                "file_path": str(log_file),
                "captured_at": datetime.now().isoformat(timespec="seconds"),
            },
        })

    upsert_ok = backend.upsert(records) if records else False
    elapsed = (time.monotonic() - start) * 1000
    log(f"[{sid}] captured {len(captures)} items -> {log_file.name} "
        f"(backend={len(records)}, ok={upsert_ok}, {elapsed:.0f}ms)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"fatal: {e}")
        sys.exit(0)
