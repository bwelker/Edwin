#!/usr/bin/env bun
/**
 * Edwin Events Daemon -- the permanent owner of port 8788.
 *
 * Architecture fix: the old index.ts was a per-session MCP stdio child that
 * ALSO bound the global webhook port. Every Claude session spawned its own
 * copy; only one won the port; when the port-owning session died, webhooks
 * flowed to a deaf process and every live session went blind.
 *
 * This daemon runs under launchd (com.edwin.events-daemon, KeepAlive=true)
 * and never belongs to any session. It:
 *   1. Receives webhook POSTs (same payload contract as the old index.ts)
 *   2. Applies the no-op filter (filter.ts) -- dropped events are counted in
 *      filter-stats.json exactly as before, never queued
 *   3. Appends DELIVERABLE events to data/events-channel/queue.jsonl, one JSON
 *      object per line with a monotonically increasing `seq` and ISO `ts`
 *   4. Maintains queue-head.json ({seq, updated_at}) so readers can start at
 *      the current head without scanning the file
 *
 * Sessions consume the queue via the rewritten index.ts (MCP reader): it
 * tails queue.jsonl and pushes events into the session over stdio. No port
 * contention, ever.
 *
 * Rotation: when queue.jsonl exceeds 10MB it is renamed to
 * queue-YYYY-MM-DD.jsonl and seq resets to 0. Readers handle this by
 * re-opening on ENOENT / size shrink / seq reset.
 *
 * Env:
 *   EVENTS_PORT        port to bind (default 8788; tests use 8799)
 *   QUEUE_PATH         queue file (default $EDWIN_HOME/data/events-channel/queue.jsonl)
 *   EVENTS_STATS_FILE  filter stats (default $EDWIN_HOME/data/events-channel/filter-stats.json)
 *   QUEUE_MAX_BYTES    rotation threshold (default 10485760; overridable for tests)
 *   EDWIN_HOME         base data directory (default ~/Edwin)
 */
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, join } from "node:path";
import { createStats, isNoopJobComplete, parseEventBody, writeStats } from "./filter.ts";

// --- Configuration -----------------------------------------------------------

const PORT = parseInt(process.env.EVENTS_PORT || "8788", 10);
const EDWIN_HOME = process.env.EDWIN_HOME || `${process.env.HOME}/Edwin`;
const QUEUE_PATH = process.env.QUEUE_PATH || `${EDWIN_HOME}/data/events-channel/queue.jsonl`;
const QUEUE_DIR = dirname(QUEUE_PATH);
const HEAD_PATH = join(QUEUE_DIR, "queue-head.json");
const STATS_FILE =
  process.env.EVENTS_STATS_FILE || `${EDWIN_HOME}/data/events-channel/filter-stats.json`;
const QUEUE_MAX_BYTES = parseInt(process.env.QUEUE_MAX_BYTES || String(10 * 1024 * 1024), 10);

const STARTED_AT = Date.now();

// --- Logging ------------------------------------------------------------------

function log(msg: string): void {
  process.stderr.write(`[events-daemon] ${new Date().toISOString()} ${msg}\n`);
}

// --- Queue state ---------------------------------------------------------------

mkdirSync(QUEUE_DIR, { recursive: true });

const stats = createStats();

/** Restore the seq counter so it stays monotonic across daemon restarts. */
function restoreSeq(): number {
  // Preferred: head file maintained by us.
  try {
    const head = JSON.parse(readFileSync(HEAD_PATH, "utf8"));
    if (typeof head.seq === "number" && head.seq >= 0) return head.seq;
  } catch {
    // fall through
  }
  // Fallback: last line of the queue file.
  try {
    const data = readFileSync(QUEUE_PATH, "utf8").trimEnd();
    if (!data) return 0;
    const lastLine = data.slice(data.lastIndexOf("\n") + 1);
    const last = JSON.parse(lastLine);
    if (typeof last.seq === "number") return last.seq;
  } catch {
    // fall through
  }
  return 0;
}

let seq = restoreSeq();

function writeHead(): void {
  try {
    writeFileSync(HEAD_PATH, JSON.stringify({ seq, updated_at: new Date().toISOString() }) + "\n");
  } catch {
    // best-effort; readers fall back to scanning the queue file
  }
}

/** Rotate queue.jsonl -> queue-YYYY-MM-DD.jsonl when it exceeds the cap. */
function rotateIfNeeded(): void {
  let size = 0;
  try {
    size = statSync(QUEUE_PATH).size;
  } catch {
    return; // no file yet, nothing to rotate
  }
  if (size <= QUEUE_MAX_BYTES) return;

  const date = new Date().toISOString().slice(0, 10);
  let target = join(QUEUE_DIR, `queue-${date}.jsonl`);
  let n = 2;
  while (existsSync(target)) {
    target = join(QUEUE_DIR, `queue-${date}-${n}.jsonl`);
    n++;
  }
  renameSync(QUEUE_PATH, target);
  seq = 0; // readers detect the reset and re-open
  writeHead();
  log(`Rotated queue (${size} bytes) -> ${target}; seq reset to 0`);
}

function enqueue(content: string, meta: Record<string, string>): number {
  rotateIfNeeded();
  seq++;
  const line = JSON.stringify({ seq, ts: new Date().toISOString(), content, meta }) + "\n";
  appendFileSync(QUEUE_PATH, line);
  writeHead();
  return seq;
}

// --- HTTP Server ----------------------------------------------------------------
//
// If the port is already taken (e.g. a stale pre-cutover index.ts child still
// holds it), do NOT crash -- retry until we get it. Crashing here is how the
// events pipeline silently died before this daemon/reader split existed.
// With launchd KeepAlive the retry loop also makes daemon restarts graceful.

const serveOptions = {
  port: PORT,
  hostname: "127.0.0.1",
  async fetch(req: Request) {
    const url = new URL(req.url);

    // Health check
    if (req.method === "GET" && url.pathname === "/health") {
      return new Response(
        JSON.stringify({
          ok: true,
          seq,
          uptime: Math.floor((Date.now() - STARTED_AT) / 1000),
        }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    if (req.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    try {
      const body = await req.text();
      const { content, meta } = parseEventBody(body, url.pathname);

      if (isNoopJobComplete(meta, content)) {
        stats.dropped++;
        const job = meta.job || "unknown";
        stats.dropped_by_job[job] = (stats.dropped_by_job[job] || 0) + 1;
        await writeStats(STATS_FILE, stats);
        log(`Filtered no-op: ${job} (${stats.dropped} dropped, ${stats.delivered} delivered since start)`);
        return new Response("ok (filtered)");
      }

      const s = enqueue(content, meta);
      stats.delivered++;
      await writeStats(STATS_FILE, stats);
      log(`Event queued: seq=${s} ${meta.event_type} from ${meta.source}`);
      return new Response("ok");
    } catch (e: any) {
      log(`Error: ${e.message}`);
      return new Response(`Error: ${e.message}`, { status: 500 });
    }
  },
};

while (true) {
  try {
    Bun.serve(serveOptions);
    log(`Listening on localhost:${PORT} (queue: ${QUEUE_PATH}, head seq: ${seq})`);
    break;
  } catch (e: any) {
    if (e?.code === "EADDRINUSE") {
      log(`Port ${PORT} in use -- retrying in 15s.`);
      await Bun.sleep(15000);
    } else {
      throw e;
    }
  }
}
