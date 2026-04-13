# Design Principles

1. **No vendor lock-in.** The LLM is swappable. The data is portable. Skills are plain markdown. Nothing depends on any single AI provider except the LLM API itself.
2. **Atomic purposes.** Each component does one thing. Connectors extract. The indexer embeds. The PM tracks commitments. Nothing is overloaded.
3. **Local-first.** All data lives on disk, in open formats (Markdown, SQLite, standard APIs). Nothing is cloud-only.
4. **The LLM is the orchestrator.** The main session talks to you and makes decisions. All work is delegated to sub-agents. Edwin decides what work to do -- sub-agents do it.
5. **The SKILL.md standard.** Procedural memory is portable markdown. Any LLM that can read text can execute a skill. No proprietary format.
6. **Know what you have.** Every tool, every skill, every service is indexed and discoverable. Edwin never says "I can't do that" about something it can do.
