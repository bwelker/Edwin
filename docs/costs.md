# What Does Edwin Cost?

## What's Free

- All 15 connectors (pure Python ETL, no LLM involved)
- Ollama embeddings (local, runs on your machine)
- Qdrant vector store (local Docker)
- Neo4j knowledge graph (local Docker)
- Plombery scheduler
- All MCP servers
- Data storage (markdown on disk)

## What Costs Money

### Required

- **Claude Code subscription** -- Edwin runs on any tier:
  - Pro: $20/mo -- good for light-to-moderate daily use
  - Max: $100/mo -- removes usage caps for heavy daily use
  - Max 20x: $200/mo -- very high usage
  - Team: $25-30/user/mo (standard) or $150/user/mo (premium with Claude Code)
  - Enterprise: custom pricing, SSO, HIPAA readiness

### Optional

- **Haiku contextual embeddings** -- improves search quality by adding AI-generated context prefixes to each chunk. ~$10/mo ongoing, ~$200 one-time for backfilling a year of data. Not required -- dense-only embeddings work well without it.
- **Limitless** ($20/mo) -- wearable pendant for ambient conversation capture. High-value data source but entirely optional.
- **Plaud** (device cost + subscription) -- recording device for in-person conversations. Optional.
- **Fireflies** (subscription varies) -- meeting transcript service. Optional.

## What Uses Tokens vs What Doesn't

**Doesn't use tokens (zero LLM cost):**

- All connector syncs
- Indexer dense + sparse embeddings (Ollama)
- Plombery scheduling
- Data storage and pipeline orchestration
- MCP server queries (Qdrant search, Neo4j queries, PM lookups)

**Uses tokens:**

- Talking to Edwin (your active session)
- Subagent work (skills, research, overnight loop)
- Haiku context prefixes (optional, cheap -- Haiku is the smallest/cheapest model)

## The Key Insight

The heavy data work is completely decoupled from the LLM. Connectors, indexing, and storage never touch your token budget. You only burn tokens when you're actually interacting with Edwin or running autonomous skills. This is why Edwin works on a $20/mo Pro subscription -- the data pipeline is free, and the LLM only processes what you ask for.
