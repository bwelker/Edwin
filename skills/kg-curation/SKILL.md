---
name: kg-curation
description: Weekly knowledge-graph curation loop -- freshness sweep against the week's reality, stale-edge invalidation, pending-merge queue drain, and org-chart temporal completeness against your authority model.
---

# KG Curation

You are Edwin. The Neo4j graph (localhost:7687) is a curated org/deal graph whose entire value is freshness -- and its documented failure mode is exactly that curation stops and nobody notices. This skill is the standing maintenance loop that prevents a lapse. Runs weekly (Plombery `skill-kg-curation`), before the devil's advocate reads the graph on first Saturdays.

**Division of labor with the neighbors:**
- **decision-ledger** owns decision follow-through. This skill mines its ledger for graph-fact candidates; it does not re-grade decisions.
- **Nightwatch / any weekday session** MAY write org/deal changes immediately via the provenance tools when spotted mid-week. This skill is the weekly reconciliation, not the only writer.
- **This skill never edits the authority model doc.** The user owns it. Doc-vs-reality mismatches are reported, not fixed.

## Write Discipline (non-negotiable)

1. **All fact writes go through `kg_add_fact` / `kg_add_entity` / `kg_invalidate`** (mcp__edwin-neo4j__). Never `kg_write` for facts or entities. ONE narrow exception: SET-only property backfill on an already-existing edge (stamping a missing `valid_at` / `source_ref`). `kg_write` must never CREATE or DELETE anything in this skill.
2. **Every `source_ref` is real**: a file path, ledger id (`dl-...`), pm-id, or message/meeting id you actually opened THIS run. A source_ref you didn't read is fabrication.
3. **Skip-when-thin**: if the evidence for a fact is one ambiguous mention, a speaker-uncertain transcript line, or your own inference -- do not write it. An unwritten fact is recoverable next week; a wrong fact poisons the graph and everything downstream that reads it.
4. **Speaker-mislabel guard**: some transcription tools mis-diarize speakers. Never source an org/deal fact from a transcript speaker attribution alone -- re-attribute by content and cross-check against messages/Teams/other transcripts before writing.
5. **Caps**: max ~10 `kg_add_fact` writes in the freshness sweep, max 10 role/reporting edges in the org-chart pass, max 2 ambiguous merges escalated to NEEDS_ATTENTION. This is a curated graph by decision -- highest-stakes facts first (org changes, deal states, gating items), never exhaustive ingestion. Hitting a cap with candidates left is fine; note the leftovers in the run record.

## Step 0: Ground

1. Run `date "+%A, %B %d, %Y"` -- never infer the date. Compute the 7-day window.
2. Freshness gauge -- `kg_query`:
   ```cypher
   MATCH ()-[r]->() RETURN max(r.created_at) AS newest_write, count(r) AS edges
   ```
   Compute days since `newest_write`. **>= 14 days = the documented failure mode recurring** -- goes in NEEDS_ATTENTION even if everything else is clean.
3. If the user maintains an org/authority model at `~/Edwin/docs/decision-flow-model.md`, read it (the org-chart source of truth -- for structure, not necessarily current reality; see Step 4).
4. `wc -l ~/Edwin/data/kg/pending-merges.jsonl` (may not exist / be empty -- that's a valid zero).

## Step 1: Freshness Sweep (cap ~10 writes)

Compare the graph against the week's reality. Sources, in scan order:

1. **Decision ledger** -- `~/Edwin/data/decisions/ledger.jsonl`. Entries with `date`, `first_seen`, or new `evidence` inside the window are prime fact candidates: deal states, org changes, project status flips. The ledger id (`dl-...`) plus the entry's own `source` path make the source_ref.
2. **Commitment aging** -- newest `~/Edwin/briefing-book/docs/3. 🎯 Action Tracker/Commitment Aging -- *.md`. Gating items that changed state this week.
3. **Org signals** -- `memory_search` with `limit: 5`, at most 3-4 queries (e.g. "hired OR resigned OR promoted OR new role this week", "contract signed OR deal closed this week"). Plus Teams/mail recency: `find ~/Edwin/data/o365/teams -name '*.md' -mtime -7` and read tails of hits for org/deal closure language. Teams files are append-updated and NOT chronological -- verify per-message `date:` frontmatter before trusting a hit.

**Write mechanics:**
- `kg_add_fact` requires both entities to exist by EXACT name -- `kg_entity_lookup` first. Genuinely new entities go through `kg_add_entity` (registry-first for Person; source_ref required). If it returns `queued_for_review`, stop there -- do not force the fact through a raw write; the merge decision comes first (maybe this run's Step 3, maybe next week's).
- Prefer `RELATES_TO` / `HOLDS_ROLE` / `REPORTS_TO` / `WORKS_AT` rel_types -- new rel_types are not covered by the `edge_name_and_fact` fulltext index and become invisible to `kg_search`.
- `valid_at` = when the fact became true in the world (the signing date, the start date), not today.
- Priority order when rationing the cap: org changes > deal/contract states > gating items > project status flips.

## Step 2: Stale-Edge Pass

For each Step 1 finding, check whether an ACTIVE edge in the graph now contradicts reality:

```cypher
MATCH (a:Entity)-[r]->(b:Entity) WHERE r.invalid_at IS NULL AND (toLower(a.name) CONTAINS '...' OR toLower(b.name) CONTAINS '...') RETURN a.name, type(r), r.fact, r.uuid, r.valid_at
```

- Same rel_type, same entity pair, new contradicting fact: just call `kg_add_fact` -- it invalidates the old edge and links supersedes/superseded_by automatically.
- Old fact simply no longer true (deal signed makes the "unsigned/in-negotiation" fact false; person left makes the role fact false) with the replacement living elsewhere or nowhere: `kg_invalidate` with `reason` + `source_ref`, THEN add the new fact if there is one. Invalidate-never-delete; you are stamping when the world changed, not erasing history.
- Do NOT invalidate on suspicion. The bar is "demonstrably changed" -- a citable source that says so.

## Step 3: Pending-Merge Drain

```bash
cd ~/Edwin/mcp-servers/neo4j && ./venv/bin/python scripts/resolve_pending_merge.py list
```

For each queued entry:
1. Evidence: `memory_search` both names (`limit: 5`) + `kg_entity_lookup` on the existing entity. You are answering one question -- are these the same real-world thing?
2. Clear verdict: `./venv/bin/python scripts/resolve_pending_merge.py resolve <line> same|different`. **Line numbers shift after each resolve -- re-run `list` before every resolve.** `same` merges in-graph and writes the name alias to the identity registry; `different` records the verdict durably. Either way the line moves to `pending-merges-resolved.jsonl`.
3. Genuinely ambiguous (evidence actively conflicts, or both names are ghosts in the corpus): leave it queued and put it in NEEDS_ATTENTION for the user -- **max 2 escalations per week**, pick the two whose resolution unblocks the most facts.

## Step 4: Org-Chart Completion

1. Pull current coverage:
   ```cypher
   MATCH (a:Entity)-[r:HOLDS_ROLE]->(b:Entity) WHERE r.invalid_at IS NULL RETURN a.name, r.fact, r.valid_at, r.source_ref
   ```
   and the same for `REPORTS_TO`.
2. Diff against the reporting-structure table in your authority model (if present). Three kinds of gap:
   - **Person in the table, no active HOLDS_ROLE edge** -- candidate to add.
   - **Active role edge missing `valid_at`** -- backfill via SET-only `kg_write` (`MATCH ()-[r]->() WHERE r.uuid = $uuid SET r.valid_at = datetime($d)`; if the edge predates uuid stamping, match by pair + rel_type + fact) with the best-evidenced date. No evidenced date = use the doc's frontmatter date and say so in the fact's source_ref basis.
   - **Person in the graph's org edges but NOT in the doc's table** (e.g. a hire the doc never got) -- the edge stays; the DOC gap goes to NEEDS_ATTENTION.
3. **Verify before writing -- the doc itself can be stale.** Anything that smells off (an "(incoming)" annotation, a person absent from the recent corpus, a role that contradicts recent meetings) gets a `memory_search` (person + role, `limit: 5`) before any write. Doc-vs-reality mismatch = NEEDS_ATTENTION for the user; write the graph from REALITY's evidence when it is solid, write nothing when it isn't. Never copy a known-stale doc row into the graph, and never edit the doc.
4. Adds: `kg_add_fact(person, "<Organization>", "HOLDS_ROLE", "<Person> holds the role of <Role> at <Organization> (per <basis>).", source_ref, valid_at=<dated from the doc or the known event -- hire date, announcement date>)`. REPORTS_TO edges likewise where reality established them. Cap 10 org edges/run.

### Org-Chart Notes

- A common failure mode: the authority-model doc lists a role as "(incoming)" but the person actually declined -- the doc row is stale. Verify against the recent corpus before adding; write the graph from reality, flag the doc gap to NEEDS_ATTENTION.
- Another: a recent hire is present in the graph (with REPORTS_TO edges) but absent from the doc entirely. Add their HOLDS_ROLE + REPORTS_TO from the dated evidence; flag the doc gap.
- Existing REPORTS_TO edges that lack `valid_at` are backfill candidates -- stamp them from the best-evidenced date.

## Step 5: Run Record

Write `~/Edwin/data/kg/curation-runs/YYYY-MM-DD.md` (create the directory if missing):

```markdown
---
date: YYYY-MM-DD
type: kg-curation-run
facts_added: N
edges_invalidated: N
merges_resolved: N
org_gaps_filled: N
graph_freshness_days: N
---
# KG Curation -- YYYY-MM-DD
## Writes (one line each: fact -- rel_type -- source_ref)
## Invalidations (one line each: fact -- reason -- source_ref)
## Merges (candidate vs existing -- verdict -- evidence basis)
## Org-chart (edges added / valid_at backfills / doc mismatches)
## Skipped (candidates left on the table: cap hits + thin-evidence skips, one line each)
```

A quiet week (0 writes, empty queue, no gaps) still writes the record -- the freshness gauge line IS the point of this skill existing.

## Self-Check (before the Completion Report)

1. Every write in the record has a source_ref you actually opened this run.
2. Every invalidation cites what changed, not what you suspect.
3. Caps respected: <=10 sweep facts, <=10 org edges, <=2 merge escalations.
4. `kg_write` usage (if any) was SET-only backfill -- zero CREATE/DELETE.
5. The authority-model doc is untouched (`git -C ~/Edwin diff --stat docs/decision-flow-model.md` is empty, if the doc exists).
6. `~/Edwin/data/kg/pending-merges.jsonl` still parses as JSONL.
7. No decider/speaker sourced from a raw transcript attribution.

## Completion Report

```
SKILL_COMPLETE: kg-curation
STATUS: success | partial | error
ARTIFACT: ~/Edwin/data/kg/curation-runs/YYYY-MM-DD.md
FACTS_ADDED: [count; one line each: fact -- source_ref, or 0]
EDGES_INVALIDATED: [count; one line each: fact -- reason, or 0]
MERGES_RESOLVED: [count; one line each: names -- verdict, or 0]
ORG_GAPS_FILLED: [count; edges added + valid_at backfills, or 0]
NEEDS_ATTENTION: [ambiguous merges (max 2), doc-vs-reality mismatches, freshness >= 14 days, or "none"]
ERRORS: [sources that failed, skipped checks, or "none"]
```

Factual, no narrative. A zero-write clean week reports success plainly -- never pad the graph to have something to show.
