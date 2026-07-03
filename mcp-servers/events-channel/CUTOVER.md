# Events Channel Cutover Runbook -- daemon/reader split

Tested on side port 8799; the live 8788 path was never touched during
development.

## What changes

| | Before (single index.ts) | After (daemon + reader) |
|---|---|---|
| Port 8788 owner | Whichever session's MCP child won the race | `com.edwin.events-daemon` LaunchAgent, permanent |
| Filtering + stats | In the session child | In the daemon (same code, moved to `filter.ts`; `filter-stats.json` shape unchanged) |
| Delivery to session | Direct from HTTP handler | Daemon appends to `data/events-channel/queue.jsonl`; reader (`index.ts`) tails it and emits over MCP stdio |
| Session crash | Webhooks hit a deaf process forever | Another session's reader takes the consumer lock within ~2 min |

Already staged (no action needed):
- `~/Library/LaunchAgents/com.edwin.events-daemon.plist` is written and linted but **not loaded**
- `$EDWIN_HOME/logs/` exists

## Pre-flight

```bash
cd $EDWIN_HOME && git status --short      # expect clean-ish; note anything odd
lsof -nP -iTCP:8788 -sTCP:LISTEN          # note the PID of the current owner (old index.ts child)
curl -s localhost:8788/health             # old health: {"status":"ok","port":8788}
```

## Step 0 -- merge the branch

The plist points at `$EDWIN_HOME/mcp-servers/events-channel/daemon.ts`, which
only exists on `main` after the merge. Do this first:

```bash
cd $EDWIN_HOME
git merge events-daemon          # fast-forward or merge commit, either is fine
```

## Step 1 -- kill the current port-owner child

```bash
lsof -nP -iTCP:8788 -sTCP:LISTEN          # confirm it's "bun .../events-channel/index.ts"
kill <PID>
```

The owning session's harness auto-respawns it (or use `/mcp` reconnect in that
session) -- and since `index.ts` is now the reader, the respawned copy binds
no port. Port 8788 is now free.

Optional hygiene: other live sessions also have old-code children stuck in the
EADDRINUSE retry loop. They are harmless (they will never win the port from
the daemon), but you can `kill` them too; each respawns as a reader.

```bash
pgrep -fl "events-channel/index.ts"       # list them all
```

## Step 2 -- load the daemon

```bash
launchctl load ~/Library/LaunchAgents/com.edwin.events-daemon.plist
```

## Step 3 -- verify the daemon owns the port

```bash
curl -s localhost:8788/health             # new shape: {"ok":true,"seq":N,"uptime":S}
lsof -nP -iTCP:8788 -sTCP:LISTEN          # command should be bun .../daemon.ts
tail $EDWIN_HOME/logs/events-daemon.log   # "Listening on localhost:8788 (queue: ...)"
```

If health still returns the OLD shape (`{"status":"ok"}`), a pre-cutover child
won the port back -- repeat Step 1, the daemon's retry loop will grab it
within 15s.

## Step 4 -- reconnect the orchestrator's reader

In the orchestrator session: run `/mcp` and reconnect `events`. The reader
logs to that session's MCP stderr:

```
[events-channel] MCP connected
[events-channel] Tailing from offset N (seq N); history skipped
[events-channel] Acquired consumer lock (pid ...)
```

Confirm the lock:

```bash
cat $EDWIN_HOME/data/events-channel/.consumer-lock.json   # pid = orchestrator's reader child
```

## Step 5 -- fire a test alert and confirm delivery

```bash
curl -s -X POST localhost:8788 -H 'Content-Type: application/json' \
  -d '{"event_type":"alert","severity":"info","source":"cutover-test","message":"Cutover test alert -- please acknowledge"}'
```

Expected: `ok` from curl, and the orchestrator session receives
`<channel source="events" event_type="alert" ...>` within ~2s and reacts.

## Step 6 -- check stats and queue advance

```bash
cat $EDWIN_HOME/data/events-channel/filter-stats.json  # delivered incremented (counters reset at daemon start -- same lifecycle as before)
cat $EDWIN_HOME/data/events-channel/queue-head.json    # seq advanced
tail -3 $EDWIN_HOME/data/events-channel/queue.jsonl    # test alert is the last line
curl -s localhost:8788/health                          # seq matches queue-head
```

Then post a known no-op and confirm it is dropped, counted, and NOT queued:

```bash
curl -s -X POST localhost:8788 -H 'Content-Type: application/json' \
  -d '{"event_type":"job_complete","job":"sys-pm-loop","status":"ok","message":"No changes detected"}'
# -> "ok (filtered)"; filter-stats dropped++ ; queue-head.json seq unchanged
```

Done. Leave the daemon loaded; it survives reboots (RunAtLoad) and crashes
(KeepAlive).

## Step 7 -- rollback (if anything is wrong)

```bash
cd $EDWIN_HOME
git revert -m 1 <merge-commit>     # or: git reset --hard <pre-merge-sha> if nothing else landed
launchctl unload ~/Library/LaunchAgents/com.edwin.events-daemon.plist
pgrep -fl "events-channel/index.ts" | awk '{print $1}' | xargs kill
```

Killed children respawn from the reverted (old) index.ts, race for 8788 as
before, one wins, and the system is byte-for-byte back to the pre-cutover
behavior. Reconnect `events` in the orchestrator session (`/mcp`) to make sure
the orchestrator's child is the port owner.

## Failure modes to know about

- **Daemon down:** launchd restarts it; senders get connection refused in the
  gap (same as today when the owner dies, except now the gap is seconds).
  Seq survives restarts via `queue-head.json`.
- **Orchestrator session dies:** its reader child dies with it; any other live
  session's reader takes the consumer lock within ~2 minutes and starts
  receiving. Events emitted into the dead session during that window are lost
  (bounded, by design).
- **No sessions running:** events accumulate in the queue. New sessions start
  at the CURRENT head -- they do not replay the backlog. If a backlog matters,
  read `queue.jsonl` manually.
- **Rotation:** at 10MB, queue.jsonl -> queue-YYYY-MM-DD.jsonl, seq resets to
  0; readers detect ENOENT/shrink/seq-reset and re-open automatically.
