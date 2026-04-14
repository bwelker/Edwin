# content-guard

Security scanner for prompt injection detection in markdown files. Scans connector output and agent-generated content before it gets indexed into the vector store.

Does NOT delete anything. Flags suspicious content and optionally quarantines copies for human review.

## Usage

```bash
# Scan a directory
content-guard scan data/o365/

# Scan a single file
content-guard scan data/o365/email/2026-04/2026-04-10.md

# JSON output
content-guard scan data/o365/ --json

# Quarantine flagged files
content-guard scan data/o365/ --quarantine /tmp/quarantine

# Scan non-markdown files
content-guard scan data/ --ext md,txt

# Verbose output (show pattern details and context)
content-guard scan data/ --verbose

# List all detection patterns
content-guard patterns

# Version
content-guard version
```

## Exit Codes

- `0` -- all files clean
- `1` -- issues found
- `2` -- usage error (bad path, bad arguments)

## Pattern Categories

### Role / Identity Hijacking
Detects attempts to override the LLM's system prompt or reassign its identity. Patterns like "ignore all previous instructions", "you are now", fake `[system]` or `[admin]` tags, and "override:" directives.

### Data Exfiltration
Detects embedded commands or instructions designed to send data to external endpoints. Includes `curl`/`wget` to URLs, "send to" with email addresses, suspicious base64 blocks, and explicit exfiltration keywords.

### Prompt Injection Framing
Detects attempts to frame content as LLM instructions rather than data. Includes role framing ("as an AI language model"), execution instructions ("execute the following"), and XML-style injection tags (`<system>`, `<instruction>`, `<prompt>`).

### Social Engineering
Detects content targeting LLMs specifically with conditional logic. Patterns like "if you are an LLM", "if you are Claude", and the Cameron Mattis canary test ("include a recipe for").

## Adding Patterns

Patterns are defined in the `PATTERNS` list at the top of the script. Each entry is a tuple:

```python
(re.compile(r"pattern_regex", re.I),
 "category",        # role_hijacking, data_exfiltration, prompt_injection, social_engineering
 "severity",        # high, medium, low
 "description")     # Human-readable description
```

Add new patterns by appending to the list. Keep severity ratings consistent:
- **high** -- likely intentional injection, should always be reviewed
- **medium** -- suspicious but could be benign in some contexts
- **low** -- worth noting, often benign (e.g., base64 blocks in technical emails)

## Quarantine

When `--quarantine <dir>` is specified:
- Flagged files are copied (not moved) to the quarantine directory with a `.quarantined` extension
- Originals are never modified or deleted
- A `manifest.json` is written listing what was quarantined and why
- Name collisions are handled automatically

## Integration

Content-guard is designed to run as a pre-indexing step in the Edwin data pipeline. It can be called by the sync runner or indexer before files enter the vector store.

Example integration with the indexer:

```bash
# Scan new connector output before indexing
content-guard scan data/o365/email/2026-04/ --json | jq '.flagged'

# If flagged > 0, quarantine and alert
content-guard scan data/ --quarantine ~/Edwin/quarantine/
```
