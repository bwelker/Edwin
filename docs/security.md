# Security Considerations

## Data Privacy

- All data stays on your machine. Nothing is sent to cloud services except what goes through the Claude Code session itself.
- Connector data is stored as plain markdown files in `data/` (gitignored).
- Memory, session summaries, and the Briefing Book are local files.
- Qdrant and Neo4j run in local Docker containers.

## Prompt Injection

Edwin ingests external data (email, messages, meeting transcripts) and stores it in searchable memory. When retrieved, this content enters the LLM's context window. This creates a theoretical prompt injection surface -- a crafted email or message could embed instructions that get retrieved alongside legitimate data.

### Mitigations

1. **Channel access control** -- Communication channels (Telegram, iMessage) are locked to a single authorized user. Nobody else can send Edwin direct instructions.
2. **System prompt identity** -- Edwin's CLAUDE.md explicitly defines identity, rules, and boundaries. The system prompt takes precedence over retrieved content.
3. **Data vs instruction framing** -- Retrieved content comes through MCP tool calls, which are framed as data returns, not user messages. The LLM is trained to treat tool results as information, not instructions.
4. **Claude's training** -- Claude includes built-in resistance to prompt injection attempts.

### Known Limitations

- These mitigations are defense-in-depth, not a guarantee. No current retrieval-augmented AI system has a perfect solution to prompt injection.
- If an attacker can send you an email with embedded instructions, and that email gets indexed and later retrieved, the instructions will appear in Edwin's context. Claude will likely ignore them, but "likely" is not "certainly."
- This is an active area of AI security research across the industry.

### Recommendations

- Be aware that any data Edwin ingests could theoretically influence its behavior if retrieved.
- Review channel access controls during setup.
- Monitor Edwin's behavior for unexpected actions.
- Keep Claude Code updated -- Anthropic continuously improves injection resistance.

## Credential Storage

- API credentials are stored in `~/.edwin/credentials/` or `.env` files.
- These are gitignored and never committed to the repository.
- Each connector documents its required credentials in [docs/connector-setup.md](connector-setup.md).
