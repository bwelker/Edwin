---
name: self-study
description: Corpus distillation -- pick one high-value stable corpus, generate a synthesis study file (narrative, current state, key decisions, anticipated Q&A with citations) into memory/distilled/ so retrieval can answer multi-hop questions that chunk retrieval misses.
---

# Self-Study (Corpus Distillation)

You are Edwin. Hybrid retrieval finds CHUNKS; it misses SYNTHESIS questions ("how do all the decisions on this project fit together", "what's the full history of this relationship") whose answers span dozens of files. This skill precomputes those answers: read one corpus end-to-end, write a distilled study file where the indexer will embed it. The existing context prefixes situate chunks within a document; this works one level up -- situating a whole corpus within the story. Adapted from the Stanford Cartridges "self-study" recipe, moved from KV-cache space to token space.

Runs as a nightwatch task ("run the self-study skill") or a standalone `run_skill`. One corpus per run -- depth beats coverage.

**Where distillates go and why:** `~/Edwin/memory/distilled/<corpus-id>.md`. The indexer's second scan root is `~/Edwin/memory` (tools/indexer/lib/config.py `MEMORY_DIR`; only `memory/archive/` is excluded), indexed as source `memory` -- which carries a query-time boost, so distillates rank well by construction. Do NOT write distillates to the harness memory dir -- the indexer does not scan it.

## Step 0: Ground and Select

1. Run `date "+%A, %B %d, %Y"` -- never infer the date.
2. Read the registry: `~/Edwin/skills/self-study/corpora.json`.
3. **Pick ONE corpus, the stalest:**
   - Any entry with `last_distilled: null` wins (oldest-listed first if several).
   - Otherwise compute overdue ratio = days since `last_distilled` / volatility horizon (high=60, medium=90, low=180 days). Highest ratio wins; below 1.0 across the board means nothing is due -- report `STATUS: success` with `CORPUS: none-due` and stop. Don't re-distill fresh corpora to look busy.
4. If the orchestrator's spawn prompt names a specific corpus id, that overrides selection.

## Step 1: Read the Corpus

1. Expand every glob in the entry's `paths` and list the matched files. Zero matches on a path goes in ERRORS (the registry may have rotted), not silently skipped.
2. **Sampling rules for big corpora** (keep the read under ~80K tokens):
   - Under ~30 files: read everything in full.
   - Bigger: read every file's frontmatter/description + the full text of (a) the most recently modified ~15 files and (b) anything a description marks as a decision, correction, or inversion. Skim the rest.
   - JSONL files (e.g. the decision ledger): parse and keep only lines relevant to the corpus topic.
3. **Cross-references:** run each of the entry's `queries` through `memory_search` with `limit: 5` -- ALWAYS limit 5. Pull in the top hits that the globs missed (transcripts, mail, session slices). These fill the gaps between memory files.
4. **Provenance guard:** some transcription tools mis-diarize speakers. Re-attribute any transcript-sourced quote by content before using it, and prefer memory files / cleaner transcripts / sessions over raw diarized transcripts for who-said-what.

## Step 2: Write the Distillate

File: `~/Edwin/memory/distilled/<corpus-id>.md`. Create `memory/distilled/` if missing.

**Overwrite semantics:** re-distillation OVERWRITES the file. A distillate is a derived artifact, not history -- unlike memories there is no supersede chain; the sources ARE the history. The indexer detects the content-hash change and re-embeds automatically.

Frontmatter:

```yaml
---
name: distilled_<corpus_id_with_underscores>
description: "One-line: what this distillate covers and its as-of date."
metadata:
  node_type: memory
  type: distilled
  corpus_id: <corpus-id>
  valid_as_of: YYYY-MM-DD        # today -- this is a synthesis snapshot
  review_after: YYYY-MM-DD       # today + volatility horizon (60/90/180d)
  sources:
    - path/or/glob/read
    - ...
---
```

`valid_as_of`/`review_after` follow the bi-temporal conventions (`~/Edwin/tools/librarian/MEMORY-CONVENTIONS.md`): a distillate is a snapshot that rots, and `librarian memory-audit` will flag it EXPIRED past `review_after` -- at which point re-distillation is the re-verification.

**Body sections -- structure FOR the chunker.** The memory source chunks with the header strategy (512 tokens / 50 overlap), splitting at headers. So every `##`/`###` header must carry context on its own ("## Project X -- Key Decisions", never bare "## Decisions"), because the header travels with the chunk:

1. `## <Corpus Title> -- Narrative` -- the story so far, told chronologically WITH DATES. How it started, the turns, where it stands. This is the "how does it all fit together" answer.
2. `## <Corpus Title> -- Current State (as of YYYY-MM-DD)` -- what is true NOW. Bullets, each independently intelligible.
3. `## <Corpus Title> -- Key Decisions` -- each decision: date, what was decided, by whom, source ref.
4. `## <Corpus Title> -- Open Questions` -- what's genuinely unresolved, with what would resolve it.
5. `## <Corpus Title> -- Anticipated Q&A` -- **the retrieval targets.** 8-15 questions someone would ACTUALLY ask (synthesis questions, cross-file questions, "wait, which was it?" confusions), each as its own `### Q: <full question text>` header, answered in 2-4 sentences with file citations. Write the questions the way the user would phrase them, not exam-style.

**Citation rule: every factual claim cites a source file** (path or memory name in parentheses). A claim you can't cite comes OUT -- a distillate that hallucinates poisons retrieval at the exact moment someone trusts it most. Where sources conflict, the later-dated correction wins and the Q&A should say so explicitly (corrections and inversions are prime Q&A material -- they're what naive chunk retrieval gets wrong).

## Step 3: Close the Loop

1. Verify the frontmatter parses: `python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1]).read().split('---')[1])" <file>`.
2. Update the registry entry's `last_distilled` to today (valid JSON check after edit).
3. The next `indexer sync` picks the file up automatically (hourly runner, or run `~/Edwin/tools/indexer/indexer sync --source memory` if you need it live tonight -- requires Python 3.12 + Ollama up; if the sync isn't practical, say so in the report and let the hourly runner do it).

## Self-Check (Before Finishing)

1. Every Q&A answer carries at least one citation, and every cited file was actually read this run.
2. No claim survives that a later-dated source corrected (check the inversions: they're where this fails).
3. Headers are self-contextualizing (chunk-safe).
4. `valid_as_of` is today, `review_after` matches the volatility horizon, `sources` list is real.
5. Registry JSON still parses.
6. No transcript-attributed quote used without content re-attribution.

## Completion Report

```
SKILL_COMPLETE: self-study
STATUS: success | partial | error
CORPUS: <corpus-id, or none-due>
ARTIFACT: ~/Edwin/memory/distilled/<corpus-id>.md
QA_COUNT: [number of anticipated Q&A entries]
SOURCES_READ: [count of files read + memory_search pulls]
INDEXED: yes | pending-next-sync
NEEDS_ATTENTION: [registry rot, source conflicts left unresolved, or "none"]
ERRORS: [dead globs, unreadable files, or "none"]
```
