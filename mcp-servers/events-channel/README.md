# events-channel

Edwin's events pipeline, split into two pieces:

- **`daemon.ts`** -- permanent owner of port 8788, run by launchd
  (`com.edwin.events-daemon`). Receives webhook POSTs, applies the no-op
  filter (`filter.ts`), appends deliverable events to
  `$EDWIN_HOME/data/events-channel/queue.jsonl` (rotates at 10MB).
  `GET /health` -> `{ok, seq, uptime}`.
- **`index.ts`** -- per-session MCP stdio reader. Binds no ports. Tails the
  queue from the current head and pushes events into the session as
  `<channel source="events">` tags. A consumer lock (`tailer.ts`) ensures
  exactly one session receives the feed, with ~2-minute automatic failover.

Env: `EVENTS_PORT` (default 8788), `QUEUE_PATH`, `EVENTS_STATS_FILE`,
`QUEUE_MAX_BYTES` (daemon only, default 10MB), `EDWIN_HOME` (base data
directory, default `~/Edwin`).

```bash
bun install
bun test          # daemon integration tests run on side port 8799
```

Cutover/rollback procedure: see `CUTOVER.md`.
