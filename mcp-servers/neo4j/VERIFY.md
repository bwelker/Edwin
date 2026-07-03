# Edwin Neo4j MCP Server -- Verification Suite

**Purpose:** After restarting Claude Code to pick up `edwin-neo4j`, run these tests.

Search is BM25 fulltext via Neo4j's native Lucene indexes -- no embeddings,
no Graphiti, no external API dependencies.

## Pre-Check

Confirm MCP server loaded -- you should have access to: `kg_search`,
`kg_search_nodes`, `kg_entity_lookup`, `kg_relationships`, `kg_query`,
`kg_write`, `kg_add_fact`, `kg_add_entity`, `kg_invalidate`, `kg_stats`

## Tests

### N1: Server Starts and Connects
**Action:** Call `kg_stats`.
**Pass:** Returns `neo4j.connected: true`, `search.mode: "bm25-fulltext"`,
`search.embeddings: false`, and non-zero `total_nodes`/`total_relationships`.

### N2: Fulltext Search -- Facts
**Action:** Call `kg_search` with a query term you know appears in an
existing relationship fact (e.g. a project or organization name in your graph).
**Pass:** Returns results with facts mentioning that term. Each result has
`fact`, `name`, `rel_type`, `source_node_uuid`, `target_node_uuid`.

### N3: Fulltext Search -- Nodes
**Action:** Call `kg_search_nodes` with a query term matching an entity name
or summary.
**Pass:** Returns nodes with names/summaries and edges with facts. Both
arrays populated when the term has coverage.

### N4: Entity Lookup
**Action:** Call `kg_entity_lookup` with the name of a known entity in your
graph.
**Pass:** Returns entity with summary and a relationships array (every
relationship type, not just RELATES_TO).

### N5: Relationships
**Action:** Call `kg_relationships` with `entity_name` set to a known entity
and `direction: "both"`.
**Pass:** Returns relationships with facts connecting that entity to others.

### N6: Read-Only Cypher -- Count
**Action:** Call `kg_query` with `cypher: "MATCH (n) RETURN count(n) as total"`.
**Pass:** Returns `[{"total": N}]` matching `kg_stats`' `total_nodes`.

### N7: Write Cypher via kg_query -- Rejected
**Action:** Call `kg_query` with `cypher: "CREATE (n:Test {name: 'test'})"`.
**Pass:** Returns `blocked: true` with an error about write operations not
being allowed.

### N8: Entity Type Counts
**Action:** Call `kg_query` with
`cypher: "MATCH (n) UNWIND labels(n) as label RETURN label, count(*) as c ORDER BY c DESC"`.
**Pass:** Returns label counts consistent with `kg_stats`' `node_counts`.

### N9: kg_add_entity -- Create, Merge, and Ambiguous Tiers
**Action:**
1. Call `kg_add_entity` with a brand-new `name` (e.g. `"Test Entity Alpha"`),
   `entity_type: "Project"`, a `summary`, and `source_ref: "verify:N9"`.
2. Call it again with the exact same `name` and a different `summary`.
3. Call it with a name that's a near-miss of an existing entity (e.g. add
   whitespace/casing variance) to exercise the `merged_high_similarity` tier.
4. Call it with a name that's a token-containment variant of an existing
   entity (e.g. `"Test Entity"` if `"Test Entity Alpha"` already exists) to
   exercise the `queued_for_review` tier.
**Pass:** Step 1 returns `action: "created"`. Step 2 returns
`action: "updated_existing"` with the summary appended, not a duplicate node.
Step 3 returns `action: "merged_high_similarity"`. Step 4 returns
`action: "queued_for_review"` and appends an entry to
`data/kg/pending-merges.jsonl` -- confirm nothing was created or merged in
the graph.

### N10: kg_add_fact -- Create, No-op, and Supersede
**Action:**
1. Call `kg_add_fact` with `source_name`/`target_name` set to the two test
   entities from N9, a `rel_type` (e.g. `"RELATES_TO"`), a `fact`, and
   `source_ref: "verify:N10"`.
2. Call it again with the identical `fact` text.
3. Call it again with the same source/target/rel_type but a DIFFERENT `fact`
   text.
**Pass:** Step 1 returns `action: "created"`. Step 2 returns
`action: "noop_duplicate"` (no new edge). Step 3 returns
`action: "created_superseding"`, and the original edge now has
`invalid_at` + `superseded_by` set (confirm via `kg_query`).

### N11: kg_invalidate
**Action:** Call `kg_invalidate` with `edge_uuid` set to an edge created in
N10, plus `reason` and `source_ref`.
**Pass:** Returns `action: "invalidated"`; the edge's `invalid_at` and
`invalidation_reason` are set. The edge is never deleted -- confirm it's
still retrievable via `kg_query`.

### N12: Neo4j Down -- Graceful Error
**Action:** Stop Neo4j, call `kg_stats`.
**Pass:** Returns `neo4j.connected: false` with an error message. No crash.
**Cleanup:** Restart Neo4j after the test, and clean up any test entities/
facts created during N9-N11 (`kg_write` with a `DETACH DELETE` against your
test uuids, or `kg_invalidate` for facts you want to keep as history).

## Notes

- `kg_write` is the raw escape hatch (CREATE/MERGE/DELETE/SET) for cleanup
  and structural maintenance the structured tools can't express -- it
  bypasses the provenance guardrails, so prefer `kg_add_fact` /
  `kg_add_entity` / `kg_invalidate` wherever they fit.
- The identity-registry bridge (`scripts/link_identity_registry.py`) only
  activates for `entity_type: "Person"` and requires
  `data/identity/registry.db` to exist; without it, `kg_add_entity` falls
  through to the similarity tiers unchanged.
