"""Edwin Memory Indexer — configuration and constants."""

import os
from pathlib import Path

# -- Paths -------------------------------------------------------------------

EDWIN_HOME  = Path(os.environ.get("EDWIN_HOME", Path(__file__).resolve().parent.parent.parent.parent))
DATA_DIR    = EDWIN_HOME / "data"
INDEXER_DIR = Path(__file__).resolve().parent.parent
STATE_FILE  = INDEXER_DIR / ".index-state.json"
LOCK_FILE   = INDEXER_DIR / ".sync.lock"

# -- Ollama (dense embeddings) -----------------------------------------------

OLLAMA_URL       = os.environ.get("EDWIN_OLLAMA_URL", "http://localhost:11434")
EMBEDDING_MODEL  = os.environ.get("EDWIN_EMBED_MODEL", "qwen3-embedding:8b")
EMBEDDING_DIM    = 2048  # qwen3-embedding:8b; adjust if using a different model
OLLAMA_TIMEOUT   = 120  # seconds per request
OLLAMA_RETRIES   = 3

# -- Qdrant ------------------------------------------------------------------

QDRANT_URL       = os.environ.get("EDWIN_QDRANT_URL", "http://localhost:" + os.environ.get("EDWIN_QDRANT_PORT", "6380"))
COLLECTION_NAME  = "edwin-memory"

# -- Sparse embeddings (fastembed) -------------------------------------------

SPARSE_MODEL = "Qdrant/bm42-all-minilm-l6-v2-attentions"

# -- Anthropic (contextual retrieval) ----------------------------------------

ANTHROPIC_MODEL  = "claude-haiku-4-5-20251001"
ANTHROPIC_RETRIES = 5
CONTEXT_MIN_DOC_TOKENS = 200  # default: skip contextualization for tiny files

# Per-source context thresholds. 0 = context everything for this source.
# Sources not listed here use CONTEXT_MIN_DOC_TOKENS.
CONTEXT_SOURCE_THRESHOLDS = {
    "fireflies":   0,  # every chunk -- meeting context is critical
    "limitless":   0,  # every chunk -- ambient conversation, highly ambiguous
    "o365-teams":  0,  # every chunk -- channel conversations lose context fast
    "teams-daily": 0,  # per-day Teams files -- same zero threshold
    "imessage":    0,  # every chunk -- short messages need situating
    "imessage-daily": 0,  # per-day iMessage files -- same zero threshold
}

# Sources that use sliding window context (load adjacent day files)
# Value is the number of messages to include from adjacent days
CONTEXT_SLIDING_WINDOW = {
    "teams-daily": 20,  # include 20 messages from prev/next day
    "imessage-daily": 20,  # include 20 messages from prev/next day
}

# Sources that use conversation-segment context.
# Instead of sending the entire file to Haiku, identify the conversation
# segment that contains each chunk and use only that segment as context.
# For iMessage: segments are message bursts separated by time gaps.
# For Teams: segments are groups of related messages.
# Value is the minimum gap in minutes to split conversations.
CONTEXT_SEGMENT_SOURCES = {
    "imessage-daily": 120,  # 2-hour gap = new conversation segment
    "teams-daily": 120,     # 2-hour gap = new conversation segment
    "imessage": 120,        # per-contact files also benefit
}

# Credentials: check env var first, then file
CREDENTIALS_FILE = Path.home() / ".edwin" / "credentials" / "anthropic" / "env"

# -- Document source filtering (relative to DATA_DIR) -----------------------
# Only these prefixes are indexed under documents/. Everything else is skipped.

# Index all document subfolders by default. Customize to limit scope.
DOCUMENTS_INCLUDE_PREFIXES = [
    "documents/",
]

# Filename patterns to skip everywhere (glob-style)
EXCLUDE_FILENAME_PATTERNS = [
    "cline_task_*",
    "*.xlsx.md",
    "*.csv.md",
    "*.tsv.md",
    "*.xls.md",
]

# -- Chars per token approximation -------------------------------------------

CHARS_PER_TOKEN = 4

# -- Source-aware chunk configs ----------------------------------------------

CHUNK_CONFIG = {
    "imessage":       {"tokens": 300,  "overlap": 30,  "strategy": "speaker"},
    "o365-mail":      {"tokens": 400,  "overlap": 40,  "strategy": "email"},
    "google-mail":    {"tokens": 400,  "overlap": 40,  "strategy": "email"},
    "o365-teams":     {"tokens": 400,  "overlap": 40,  "strategy": "teams"},
    "o365-calendar":  {"tokens": 512,  "overlap": 50,  "strategy": "default"},
    "o365-sharepoint":{"tokens": 512,  "overlap": 50,  "strategy": "header"},
    "o365-onedrive":  {"tokens": 512,  "overlap": 50,  "strategy": "default"},
    "google-calendar":{"tokens": 512,  "overlap": 50,  "strategy": "default"},
    "fireflies":      {"tokens": 600,  "overlap": 60,  "strategy": "sections"},
    "limitless":      {"tokens": 600,  "overlap": 60,  "strategy": "speaker"},
    "jira":           {"tokens": 512,  "overlap": 50,  "strategy": "header"},
    "confluence":     {"tokens": 512,  "overlap": 50,  "strategy": "header"},
    "bitbucket":      {"tokens": 512,  "overlap": 50,  "strategy": "header"},
    "sessions":       {"tokens": 600,  "overlap": 60,  "strategy": "turns"},
    "calls":          {"tokens": 512,  "overlap": 50,  "strategy": "default"},
    "browser":        {"tokens": 512,  "overlap": 50,  "strategy": "default"},
    "documents":      {"tokens": 512,  "overlap": 50,  "strategy": "header"},
    "notes":          {"tokens": 512,  "overlap": 50,  "strategy": "header"},
    "photos":         {"tokens": 512,  "overlap": 50,  "strategy": "default"},
    "screentime":     {"tokens": 512,  "overlap": 50,  "strategy": "default"},
    "default":        {"tokens": 512,  "overlap": 50,  "strategy": "default"},
}

# -- Source type detection from path -----------------------------------------
# Maps path components under DATA_DIR to source types.
# Try 2-part match first (e.g., "o365/mail"), then 1-part.

SOURCE_MAP = {
    "imessage":            "imessage",
    "imessage/daily":      "imessage-daily",
    "o365/mail":           "o365-mail",
    "o365/teams":          "o365-teams",
    "o365/teams-daily":    "teams-daily",
    "o365/calendar":       "o365-calendar",
    "o365/sharepoint":     "o365-sharepoint",
    "o365/onedrive":       "o365-onedrive",
    "google/mail":         "google-mail",
    "google/calendar":     "google-calendar",
    "fireflies":           "fireflies",
    "limitless":           "limitless",
    "atlassian/jira":      "jira",
    "atlassian/confluence": "confluence",
    "atlassian/bitbucket": "bitbucket",
    "sessions":            "sessions",
    "calls":               "calls",
    "browser":             "browser",
    "documents":           "documents",
    "notes":               "notes",
    "photos":              "photos",
    "screentime":          "screentime",
}

# -- Contextual retrieval prompt (from Anthropic paper) ----------------------

CONTEXT_PROMPT = """<document>
{document}
</document>
Here is the chunk we want to situate within the whole document
<chunk>
{chunk}
</chunk>
Please give a short succinct context to situate this chunk within the overall document for the purposes of improving search retrieval of the chunk. Answer only with the succinct context and nothing else."""
