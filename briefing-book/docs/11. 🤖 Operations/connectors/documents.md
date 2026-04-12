---
type: connector-docs
connector: documents
---

# Documents Connector

Scans local filesystem directories for documents and extracts their text content into markdown for indexing.

## Quick Setup

No configuration needed -- reads directly from the local filesystem.

**Scan roots:**
- `~/Documents`
- `~/Desktop`
- `~/Pictures`
- `~/Library/Mobile Documents/com~apple~CloudDocs` (iCloud Drive)

## What It Captures

Text content extracted from: PDF, DOCX, XLSX, PPTX, MD, TXT, CSV, RTF, PAGES, KEY files.

Maximum file size: 50 MB.

## How It Works

- Scans all four root directories recursively
- Skips known non-content directories (.git, node_modules, venv, build, etc.)
- Uses content-addressed hashing (SHA256) for change detection and move tracking
- Text extraction per format:
  - **PDF**: pdfplumber
  - **DOCX**: python-docx
  - **XLSX**: openpyxl (sheet names + cell values)
  - **PPTX**: python-pptx (falls back to macOS textutil)
  - **RTF, PAGES, KEY**: macOS textutil
  - **MD, TXT, CSV**: direct read
- Prunes stale entries when source files are deleted or moved
- Incremental -- only re-processes files with changed content hashes

## Output Format

```
~/Edwin/data/documents/
  {sanitized-relative-path}.md
```

Each output file contains YAML frontmatter with source path, hash, and timestamps, followed by the extracted text content.

## Cadence

Daily via scheduler (9 PM).
