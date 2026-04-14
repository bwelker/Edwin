# Deployment Recommendations

## Run Edwin on a Dedicated Machine

Edwin is designed to run as a persistent system. Connectors sync on schedule, Plombery runs pipelines around the clock, Docker containers (Qdrant, Neo4j) need to stay up, and the overnight loop runs skills while you sleep. If you run Edwin on your daily laptop, everything stops when you close the lid -- scheduled syncs, morning briefs, overnight work, all of it.

**Recommended setup:** A dedicated Mac that stays on 24/7. A Mac Mini is ideal -- low power draw (~5W idle), small footprint, and enough horsepower for everything Edwin needs. Any Mac you're not carrying around daily works.

**How it works in practice:**
- The Mac Mini runs Edwin, Docker, Ollama, Plombery, and all connectors
- You interact with Edwin from your phone, tablet, or laptop via Telegram or iMessage
- The channel connects you to the always-on instance remotely -- you don't need to be sitting at the machine
- Your data stays on the Mac Mini, not in the cloud

This is why channels matter. Telegram and iMessage aren't just convenience features -- they're the architecture. Your phone is the interface. The dedicated machine is the brain.

## What Runs on the Dedicated Machine

| Component | Why it needs to stay on |
|-----------|------------------------|
| Docker (Qdrant + Neo4j) | Vector store and knowledge graph must be available for search |
| Ollama | Local embeddings for the indexer |
| Plombery | Schedules all connector syncs, skills, and system tasks |
| Events channel | Receives job notifications and pushes them to the active session |
| Claude Code session | The main Edwin session that responds to you and delegates work |

## What You Can Run Anywhere

| Component | Notes |
|-----------|-------|
| Telegram app | Talk to Edwin from your phone, tablet, desktop -- anywhere |
| iMessage | If configured with BlueBubbles (advanced setup) |
| Obsidian | View and edit the Briefing Book from any synced device |

## Minimum Hardware

Edwin runs well on any Apple Silicon Mac. Recommended specs:
- Apple Silicon (M1 or later)
- 16GB RAM (8GB works but tight with Ollama + Docker)
- 256GB storage minimum (data grows over time)
- Reliable internet connection (for API calls and connector syncs)

A Mac Mini M2 with 16GB RAM is the sweet spot -- ~$600 new, draws almost no power, and runs everything Edwin needs.
