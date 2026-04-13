# Memory Model

## Five Memory Tiers

Edwin's memory is modeled on human cognition -- five systems that mirror how your brain actually stores and retrieves information:

| Type | Purpose | System | How it works |
|------|---------|--------|-------------|
| **Semantic** | What things mean | Qdrant vectors + Ollama embeddings | Dense (+ optional sparse) vector search across all your data |
| **Episodic** | What happened | Neo4j knowledge graph | Entity relationships, multi-hop reasoning, timeline queries |
| **Procedural** | How to do things | SKILL.md files | Portable markdown instructions any LLM can execute |
| **Prospective** | What needs to happen | PM server (SQLite) | Commitments, tasks, intentions with due dates and owners |
| **Working** | What matters right now | Context window + session state | Boot sequence, session summaries, conversation-state.md, morning brief |

Working memory is more than the LLM's context window. It's a full system: session state that survives crashes, session summaries for continuity across conversations, a boot sequence that reconstructs context on startup, and a morning brief that primes the most important information first.

## Embedding Options

Edwin supports three tiers of search quality, each opt-in:

| Tier | What | Cost | Requirement |
|------|------|------|-------------|
| Dense only | Ollama embeddings | Free | Ollama (included in setup) |
| Dense + Sparse | Adds BM42 hybrid search | Free | Python 3.12 + fastembed |
| Dense + Sparse + Context | Adds Haiku context prefixes | Varies with data volume | Anthropic API key |

Default is dense-only. Upgrade anytime by asking Edwin.
