# Contributing to Edwin

Edwin is built by people who use AI agents to do real work. If that's you, you're in the right place.

## Philosophy

I built Edwin to be an executive assistant. The biggest challenge was giving it enough context to work autonomously -- so I kept building connectors, memory systems, and skills until it could handle the mundane daily work that used to eat my time or someone else's. The best contributions come from the same place -- a real problem you solved, a connector you needed, a workflow you automated.

You have an AI agent. It can read this codebase, understand the patterns, and help you build on top of them. I encourage you to use it.

## Discussions

Questions, ideas, architecture conversations, and show-and-tell of what you've built on top of Edwin are all welcome in Discussions. This is the best place to start if you're not sure whether something should be a PR.

## Bugs

If something is broken before you can get Edwin running (setup.sh fails, Docker won't start, dependency issues), please open an Issue. Those are infrastructure problems and I want to know about them.

Once Edwin is running and you have your agent working, I'd love it if you took a crack at fixing bugs you find. Most bugs in Edwin are fixable by the same agent that runs Edwin -- that's kind of the point. A clear bug report is always welcome. A bug report with a fix is even better.

1. Describe it clearly (what happened, what you expected, steps to reproduce)
2. If you can, ask your agent to help fix it
3. Submit the fix as a PR

## Feature Ideas

The best way to propose a feature:

1. Open a Discussion to talk about the idea and get feedback
2. Build it (your agent can help)
3. Test it
4. Submit a PR

I'm much more likely to merge a working implementation than to build something from a feature request. That said, good ideas are good ideas -- if you have one but don't have time to build it, a Discussion is still welcome.

## Pull Requests

- Solve a real problem you actually had
- Include tests or a clear test plan
- Don't break existing functionality
- Follow existing code patterns
- Open a Discussion first if the change is significant

## What I'm Looking For

- New connectors for data sources I haven't covered
- Skills that automate useful workflows
- MCP tools that add new capabilities
- Vector and graph memory expertise -- if you know Qdrant, Neo4j, or retrieval systems and can improve recall quality, I'd love the help
- Bug fixes and reliability improvements
- Documentation improvements
- Platform support beyond macOS (Windows/Linux connectors)

Welcome aboard.
