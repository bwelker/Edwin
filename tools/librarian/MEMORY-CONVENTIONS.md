# Memory Layer Conventions -- Bi-Temporal Validity

The curated memory layer (`memory/*.md` in the Claude Code project directory
for this Edwin instance, plus the `MEMORY.md` index -- see `EDWIN_MEMORY_LAYER`
/ the auto-detect logic in `tools/librarian/librarian`) holds facts that
silently rot: org changes, project status flips, corrected facts. A memory
records *when something was learned*, but nothing used to record *whether it
is still true*. These conventions add that second time axis (event time vs.
validity time -- the Zep bi-temporal model), and `librarian memory-audit`
enforces them deterministically.

All fields are **additive and backward-compatible**. A file without them is simply
"unaudited" -- nothing breaks, the audit just reports it.

## Frontmatter fields

Fields live inside the `metadata:` block when the file has one; files using
flat top-level frontmatter (`type:` at top level) put them at top level. The
audit checks both locations.

### `valid_as_of: YYYY-MM-DD` (every memory file)

The date the fact was **last verified true against reality** -- not when the file
was written. Update it whenever you re-verify the fact (nightwatch drift checks,
manual review, or any session where the fact is confirmed live). Backfillable
from dates in the file's own text / `originDate` where knowable; otherwise the
audit date.

### `valid_basis: assumed` (optional)

Present only when `valid_as_of` was stamped without evidence (e.g. a backfill
pass stamped files with no internal dates using the audit date). An
`assumed` basis means "never actually verified" -- these are prime candidates
for nightwatch re-verification. Remove the field when the fact is genuinely
re-verified (and bump `valid_as_of`).

### `review_after: YYYY-MM-DD` (optional -- known-volatile facts)

Explicit expiry. Past this date the fact is **EXPIRED**: it must be re-verified
before being trusted or repeated. Set it on facts that decay on a schedule:

| Fact class | Suggested horizon |
|---|---|
| Org structure / roles / reporting lines | +90 days |
| Project status (active/blocked/pending) | +60 days |
| Pricing / billing / plan terms | +60 days |
| Parked or deferred items | +180 days |
| Schedules, recurring logistics | +90 days |

Re-verifying means: check recent corpus data (`memory_search`, targeted greps of
`data/`), confirm or correct the fact, bump `valid_as_of`, and push
`review_after` forward.

### `superseded_by: <memory-name>` (optional -- the file is history)

The fact was corrected or replaced; this file points at its replacement (file
stem or `name:` value). Superseded files also **move to `memory/archive/`** per
the existing never-delete convention: corrections supersede, they don't erase.
A superseded file still sitting in the active directory is an audit issue.

## Type volatility (audit defaults)

The audit treats `metadata.type` (or top-level `type`) as a volatility signal.
The map is a visible CONFIG in `tools/librarian/librarian` (`MEMORY_VOLATILITY`):

- `project`, `reference` -> **volatile**: `valid_as_of` older than 90 days
  (`MEMORY_STALE_DAYS`) is flagged AGING even without a `review_after`.
- `user`, `feedback` -> **stable**: no age-based flag; only an explicit
  `review_after` can expire them.

## The audit -- `librarian memory-audit`

Deterministic, no LLM. Reports:

- **EXPIRED** -- `review_after` in the past (exit code 2; ALERTs in systems-report)
- **AGING** -- volatile type with `valid_as_of` older than `MEMORY_STALE_DAYS`
- **UNAUDITED** -- no `valid_as_of` at all
- **assumed basis** -- counted in the summary (verified vs assumed split)
- **SUPERSEDED** -- `superseded_by` set but the file is still active (should be archived)
- **DANGLING** -- `[[wikilink]]` or `superseded_by` pointing at no active or archived memory
- **INDEX** -- `MEMORY.md` lines with no file / files with no index line
- **PARSE** -- unreadable frontmatter

Exit codes: `2` = at least one EXPIRED fact; `1` = structural issues (dangling /
index / superseded-in-place / parse); `0` = clean. AGING and UNAUDITED are
warnings only -- they queue work, they don't fail the run.

Every run appends a summary line to
`memory/librarian/.memory-audit-history.jsonl` (under `EDWIN_HOME`). The audit
runs as part of `librarian full` and feeds a section of the nightly
systems-report.

## Re-verification loop (nightwatch)

"Memory drift re-verification" is a standing nightwatch auto-execute task type
(see `skills/overnight-loop/SKILL.md`): pick 2-3 EXPIRED or oldest-volatile
memories, re-verify each against recent corpus data (`memory_search` limit 5 +
targeted greps), then either bump `valid_as_of` (still true) or correct the
fact. Corrections follow the never-delete rule: write the corrected memory,
mark the old one `superseded_by`, move it to `memory/archive/`, and update the
`MEMORY.md` index line.
