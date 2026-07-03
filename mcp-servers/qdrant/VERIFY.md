# Edwin Qdrant MCP Server — Verification Suite

**Purpose:** After restarting Claude Code to pick up the `edwin-qdrant` MCP
server, run these tests to verify it works correctly.

## Pre-Check

Before running tests, confirm the MCP server loaded:
- You should have access to three tools: `memory_search`, `memory_get`, `memory_status`
- If these tools are not visible, the MCP server failed to start. Check
  `$EDWIN_HOME/.mcp.json` exists and `node $EDWIN_HOME/mcp-servers/qdrant/index.js`
  runs without error.

## Tests

### Q1: Server Starts and Connects
**Action:** Call `memory_status` with no arguments.
**Pass:** Returns JSON with `qdrant.connected: true` and `ollama.connected: true`.
Vector count should be non-zero and roughly match your indexed corpus size.

### Q2: Semantic Search Works
**Action:** Call `memory_search` with a query you know has coverage in your
indexed data.
**Pass:** Returns results array with at least 1 result and
`search_mode: "hybrid-rerank"` (or `hybrid-rrf` if the reranker is down, or
`dense-fallback` if the whole sparse helper is down). All non-null `score`
values >= 0.55 (dense cosine floor); sparse-only hits carry `score: null`
with a `fusedScore`. In `hybrid-rerank` mode every returned hit carries a
`rerankScore`, the response includes `top_rerank_score` + `rerank_model`,
and results are ordered by `rerankScore` descending.

### Q3: Source Filter
**Action:** Call `memory_search` with a query and `sources: [<one of your
connector names>]`.
**Pass:** All returned results have that `source`. No results from other
sources.

### Q4: Date Filter
**Action:** Call `memory_search` with a query and `dateFrom: "<a recent
ISO date>"`.
**Pass:** All returned results have `date >= dateFrom`.

### Q5: Temporal Phrase Rewriting
**Action:** Call `memory_search` with a query containing an unambiguous
leading or trailing temporal phrase, e.g. `"what did we discuss about the
project last week"`.
**Pass:** The response includes `rewritten_query` (the phrase stripped) and
`parsed_range` (the resolved `dateFrom`/optional `dateTo`). Results are
filtered to that date range. See `test/temporal.test.js` for the exact
phrase grammar (leading phrases require a comma; possessives and
mid-sentence phrases are never rewritten).

### Q6: People Filter
**Action:** Call `memory_search` with a query and `people: ["<a name that
appears in your indexed content>"]`.
**Pass:** All returned result snippets contain that name (case-insensitive).
Note: this uses text-match on chunk content since the `people` payload
field isn't populated by the indexer yet.

### Q7: memory_get — Known File
**Action:** Pick a `path` from one of the Q2 search results. Call
`memory_get` with that `filePath`.
**Pass:** Returns non-empty `text` field with actual file content. `lines`
count > 0.

### Q8: memory_get — Missing File
**Action:** Call `memory_get` with `filePath: "/nonexistent/path/fake.md"`.
**Pass:** Returns `text: ""` and `error: "File not found"`. No crash, no
`isError: true`.

### Q9: memory_status Accuracy
**Action:** Compare `memory_status` output against direct Qdrant API:
```
curl -s http://localhost:6333/collections/edwin-memory | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['result']['vectors_count'])"
```
(Adjust the port to match `QDRANT_URL`/`EDWIN_QDRANT_PORT` if you've
overridden the default.)
**Pass:** Vector count from `memory_status` matches curl output (±100,
accounting for in-flight indexing).

### Q10: Ollama Down — Graceful Error
**Action:** Stop Ollama (`pkill ollama` or `launchctl stop ollama`), then
call `memory_search` with `query: "test"`.
**Pass:** Returns `isError: true` with a clear error message mentioning
Ollama or connection. Does NOT crash the MCP server.
**Cleanup:** Restart Ollama after this test (`ollama serve &` or equivalent).

### Q11: Reranker/Sparse Helper Down — Graceful Degradation
**Action:** Kill the running `sparse_helper.py` process (or set
`RERANK_DISABLED=1` and restart the server), then call `memory_search`.
**Pass:** Search still returns results (`search_mode` degrades to
`hybrid-rrf` or `dense-fallback` as appropriate). No crash. The MCP server
logs the degradation to stderr and continues serving.

### Q12: Concurrent Access
**Action:** While the indexer is running (or manually trigger a Qdrant
write), call `memory_search`.
**Pass:** Search returns results normally. No errors about locked
collections or timeouts.
