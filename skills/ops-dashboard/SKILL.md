---
name: ops-dashboard
description: Generate operational status pages for Briefing Book
---

You are Edwin, generating the operations dashboard -- 4 status pages covering pipeline health, indexing coverage, memory systems, and capability inventory.

## Output

Write 4 files into `~/Edwin/briefing-book/docs/11. Operations/`:

1. **Pipeline Status.md** -- connector health
2. **Indexing Status.md** -- vector coverage
3. **Memory Health.md** -- Qdrant, Neo4j, Ollama, PM
4. **Capabilities.md** -- skills, pipelines, MCP servers

## Page 1: Pipeline Status

Frontmatter:
```yaml
---
date: <today YYYY-MM-DD>
type: ops-dashboard
auto-updated: hourly
---
```

For each connector (o365, google, imessage, limitless, browser, notes, sessions, atlassian, fireflies, calls, screentime, photos, documents):

1. List sub-types by scanning subdirectories under `~/Edwin/data/<connector>/`
2. Count markdown files per sub-type: `find ~/Edwin/data/<connector>/<subtype>/ -name "*.md" | wc -l`
3. Get last sync time from the most recent file's mtime: `find <dir> -name "*.md" -exec stat -f '%m %N' {} + | sort -rn | head -1` then convert epoch with `date -r <epoch>`
4. Determine status using these cadences:
   - o365: 15 min (mail), 15 min (calendar), 15 min (teams/teams-daily), 60 min (sharepoint)
   - google: 30 min (mail), 30 min (calendar)
   - imessage: 60 min
   - limitless: 60 min
   - browser: 2 hr
   - notes: 2 hr
   - sessions: 2 hr
   - atlassian: 2 hr
   - fireflies: daily
   - calls: daily
   - screentime: daily
   - photos: daily
   - documents: daily
5. Status: **Fresh** if last sync is within 2x expected cadence, **Stale** if overdue

Format:
```
## Pipeline Status

*Generated: <timestamp>*

| Source | Sub-type | Files | Last Sync | Status |
|--------|----------|------:|-----------|--------|
| o365 | mail | 4,546 | 2026-04-05 09:28 | Fresh |
...
```

## Page 2: Indexing Status

Parse `~/Edwin/tools/indexer/.index-state.json`:
- The `files` key maps relative paths to objects with `{hash, chunks, indexed_at, context_done}`
- Group by source (first path segment, e.g. `o365`, `google`, `imessage`)
- Count files and total chunks per source
- Count files where `context_done` is true (these have LLM context prefixes)
- Count total chunks for context_done files vs non-context files

Also count total markdown files on disk per source to compute embedding coverage %.

The page should have TWO tables:

**Table 1: Embedding Coverage** (are files in Qdrant?)
```
| Source | Indexed Files | Disk Files | Chunks | Embedding Coverage |
```

**Table 2: Context Coverage** (do chunks have LLM-generated context prefixes?)
This is the critical quality metric. Context prefixes dramatically improve search relevance.
```
| Source | Files | Context Done | Context % | Chunks | Est. Context Chunks |
```

Format:
```
## Indexing Status

*Generated: <timestamp> | Embedding model: configured in indexer | Context: LLM context prefixes*

### Embedding Coverage
| Source | Indexed Files | Disk Files | Chunks | Coverage |
|--------|-------------:|----------:|-------:|---------:|
| o365 | 8,197 | 8,197 | 20,369 | 100% |
...
**Totals:** X files indexed / Y on disk -- N chunks

### Context Prefix Coverage
| Source | Files | Context Done | Context % | Priority |
|--------|------:|------------:|---------:|----------|
| fireflies | 177 | 177 | 100% | -- |
| imessage | 1,385 | 1,111 | 80% | HIGH |
...
**Totals:** X / Y files with context (Z%)

**Priority targets:** List sources under 90% that are high-value (conversational data: imessage, limitless, teams, sessions, fireflies).
```

## Page 3: Memory Health

Query each system:

**Qdrant:**
```bash
curl -s localhost:6333/collections/edwin-memory
```
Extract: points_count, status, segment count, vector config.

**Neo4j:**
```bash
curl -s -u neo4j:<password> -H "Content-Type: application/json" \
  -d '{"statements":[{"statement":"MATCH (n) RETURN count(n) as nodes"},{"statement":"MATCH ()-[r]->() RETURN count(r) as rels"},{"statement":"MATCH (n) RETURN DISTINCT labels(n) as label, count(n) as cnt ORDER BY cnt DESC LIMIT 10"}]}' \
  http://localhost:7474/db/neo4j/tx/commit
```

**Ollama:**
```bash
curl -s localhost:11434/api/tags
```

**PM:** Use `pm_list` MCP tool to get all items, then count by status and type.

Format:
```
## Memory Health

*Generated: <timestamp>*

### Qdrant (Vector Store)
| Metric | Value |
|--------|-------|
| Points | 153,256 |
| Status | green |
...

### Neo4j (Knowledge Graph)
| Metric | Value |
|--------|-------|
| Nodes | 751 |
| Relationships | 3,394 |
...

### Ollama (Embeddings)
| Model | Size |
|-------|------|
| qwen3-embedding:8b | 4.7 GB |

### Prospective Memory
| Status | Count |
|--------|------:|
| open | X |
| done | Y |
...
```

## Page 4: Capabilities

**Skills:** Read `~/Edwin/docs/SKILLS.md` and list each skill with its trigger.

**Plombery Pipelines:** Read `~/Edwin/tools/plombery/app.py` and extract all `register_pipeline()` calls. List id, name, and trigger schedule.

**MCP Servers:** List available local servers (Qdrant, Neo4j, PM, etc.) plus cloud servers.

**PM Stats:** Reuse the PM data from Page 3 -- total items, open, overdue, by type.

Format:
```
## Capabilities

*Generated: <timestamp>*

### Skills
| Skill | Purpose | Trigger |
|-------|---------|---------|
...

### Plombery Pipelines
| ID | Name | Schedule |
|----|------|----------|
...

### MCP Servers
**Local:**
- Qdrant (localhost:6333) -- semantic memory
...

**Cloud:**
- Atlassian -- Jira, Confluence, Bitbucket
...

### PM Summary
| Type | Open | Done | Total |
|------|-----:|-----:|------:|
...
```

## Publishing

After writing all 4 pages:
```bash
cd ~/Edwin/briefing-book && python3 scripts/obsidian-publish --all
```

## Completion Report

```
SKILL_COMPLETE: ops-dashboard
STATUS: success | partial | error
ARTIFACTS: 4 pages in 11. Operations/
PUBLISHED: yes | no
NEEDS_ATTENTION: [any issues, or "none"]
ERRORS: [any errors, or "none"]
```
