/**
 * Edwin Events Channel -- queue tailer + consumer lock.
 *
 * The session-side half of the listener/reader split. The
 * daemon (daemon.ts) owns port 8788 and appends deliverable events to
 * queue.jsonl; this module tails that file and hands new events to a
 * callback. index.ts wires the callback to the MCP channel notification.
 *
 * Semantics:
 *   - Durable cursor (.consumer-cursor.json {seq, ts, updated_at}): the lock
 *     holder persists its consumed position as it emits. On a fresh start, if a
 *     recent cursor exists, the tailer replays the gap -- events that landed
 *     while zero sessions were alive -- BOUNDED to the last `replayMaxMs`
 *     (default 2h) so a long-idle machine never floods a new session with stale
 *     history. If no cursor exists (or it's older than the window), the tailer
 *     falls back to the CURRENT head exactly as before. This closes the silent
 *     event-loss window when a session dies and a new one starts later.
 *     The cursor is reader-side only -- the daemon is untouched.
 *   - Consumer lock (.consumer-lock.json {pid, sessionStart, heartbeat}):
 *     only the lock holder emits events to its session. Holder refreshes the
 *     heartbeat every 30s. Non-holders check every 30s and take over when the
 *     heartbeat is staler than 120s, using write-with-verify (write own
 *     claim, wait 1s, confirm own pid survived) to avoid races. A holder that
 *     loses the lock stops emitting. Net effect: single-orchestrator
 *     semantics with automatic failover -- a dead session can never hold the
 *     feed for more than ~2 minutes.
 *   - Rotation: if the queue file disappears, shrinks, or seq resets, the
 *     tailer re-opens from offset 0 of the new file.
 *
 * No MCP imports here -- this module is exercised directly by the test
 * harness in test/.
 */
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

export interface QueueEvent {
  seq: number;
  ts: string;
  content: string;
  meta: Record<string, string>;
}

export interface TailerOptions {
  queuePath: string;
  /** Defaults to queue-head.json next to the queue file. */
  headPath?: string;
  /** Defaults to .consumer-lock.json next to the queue file. */
  lockPath?: string;
  /** Defaults to .consumer-cursor.json next to the queue file. */
  cursorPath?: string;
  /**
   * Bounded-replay window, ms (default 7_200_000 = 2h). On fresh start, gap
   * events older than this are NOT replayed; the tailer falls back to head.
   * Set to 0 to disable replay entirely (legacy skip-to-head behavior).
   */
  replayMaxMs?: number;
  /** Called for each new event while this tailer holds the consumer lock. */
  emit: (event: QueueEvent) => Promise<void> | void;
  /** Optional logger (stderr in production). */
  log?: (msg: string) => void;
  /** Queue poll interval, ms (default 2000). */
  pollMs?: number;
  /** Heartbeat refresh / lock check interval, ms (default 30000). */
  heartbeatMs?: number;
  /** Heartbeat staleness threshold for takeover, ms (default 120000). */
  staleMs?: number;
  /** Verify delay after writing a lock claim, ms (default 1000). */
  verifyMs?: number;
}

interface ConsumerLock {
  pid: number;
  sessionStart: string;
  heartbeat: string;
}

interface ConsumerCursor {
  /** Last seq this consumer handed to `emit`. */
  seq: number;
  /** ISO ts of that event (used to bound the replay window). */
  ts: string;
  /** ISO ts the cursor was last persisted. */
  updated_at: string;
}

export class QueueTailer {
  private readonly queuePath: string;
  private readonly headPath: string;
  private readonly lockPath: string;
  private readonly cursorPath: string;
  private readonly replayMaxMs: number;
  private readonly emit: TailerOptions["emit"];
  private readonly log: (msg: string) => void;
  private readonly pollMs: number;
  private readonly heartbeatMs: number;
  private readonly staleMs: number;
  private readonly verifyMs: number;

  private readonly sessionStart = new Date().toISOString();
  private offset = 0;
  private lastSeq = 0;
  private holder = false;
  private stopped = false;
  private pollTimer: ReturnType<typeof setInterval> | null = null;
  private lockTimer: ReturnType<typeof setInterval> | null = null;
  private polling = false;

  constructor(opts: TailerOptions) {
    this.queuePath = opts.queuePath;
    const dir = dirname(opts.queuePath);
    mkdirSync(dir, { recursive: true }); // lock/head live here; daemon may not have started yet
    this.headPath = opts.headPath ?? join(dir, "queue-head.json");
    this.lockPath = opts.lockPath ?? join(dir, ".consumer-lock.json");
    this.cursorPath = opts.cursorPath ?? join(dir, ".consumer-cursor.json");
    this.replayMaxMs = opts.replayMaxMs ?? 7_200_000; // 2h bounded replay
    this.emit = opts.emit;
    this.log = opts.log ?? (() => {});
    this.pollMs = opts.pollMs ?? 2000;
    this.heartbeatMs = opts.heartbeatMs ?? 30_000;
    this.staleMs = opts.staleMs ?? 120_000;
    this.verifyMs = opts.verifyMs ?? 1000;
  }

  get isHolder(): boolean {
    return this.holder;
  }

  get currentSeq(): number {
    return this.lastSeq;
  }

  /** Start tailing: position (bounded replay or head), attempt lock, begin loops. */
  async start(): Promise<void> {
    this.positionStart();
    await this.tryAcquireLock();
    this.pollTimer = setInterval(() => void this.poll(), this.pollMs);
    this.lockTimer = setInterval(() => void this.lockTick(), this.heartbeatMs);
  }

  stop(): void {
    this.stopped = true;
    if (this.pollTimer) clearInterval(this.pollTimer);
    if (this.lockTimer) clearInterval(this.lockTimer);
    this.pollTimer = null;
    this.lockTimer = null;
  }

  // --- Tail position -----------------------------------------------------------

  /**
   * Decide where to start tailing. If a durable cursor exists and is within the
   * bounded-replay window, replay the gap (events seq > cursor.seq that arrived
   * while no session was alive). Otherwise fall back to the current head -- the
   * original skip-history behavior. Backward-compatible: no cursor => head.
   */
  private positionStart(): void {
    const cursor = this.replayMaxMs > 0 ? this.readCursor() : null;
    if (cursor && this.tryReplayFromCursor(cursor)) return;
    this.skipToHead();
  }

  /** Position at the current head: byte offset = file size, seq from head file. */
  private skipToHead(): void {
    try {
      this.offset = statSync(this.queuePath).size;
    } catch {
      this.offset = 0; // no queue yet -- daemon will create it
    }
    try {
      const head = JSON.parse(readFileSync(this.headPath, "utf8"));
      if (typeof head.seq === "number") this.lastSeq = head.seq;
    } catch {
      this.lastSeq = 0;
    }
    this.log(`Tailing from offset ${this.offset} (seq ${this.lastSeq}); history skipped`);
  }

  /**
   * Position to replay the gap after `cursor`. Scans the queue file (cheap --
   * one read, queue is rotation-capped at 10MB) for the first line with
   * seq > cursor.seq whose ts is within the replay window. Sets offset/lastSeq
   * so poll() picks up from there. Returns false (=> fall back to head) when:
   *   - the cursor itself is older than the replay window (long-idle machine),
   *   - the queue file is missing/unreadable,
   *   - no in-window gap events exist past the cursor,
   *   - the queue's seq range no longer contains the cursor (rotation since).
   */
  private tryReplayFromCursor(cursor: ConsumerCursor): boolean {
    const cutoff = Date.now() - this.replayMaxMs;
    const cursorTs = Date.parse(cursor.ts);
    if (Number.isNaN(cursorTs) || cursorTs < cutoff) {
      this.log(`Cursor seq ${cursor.seq} (${cursor.ts}) older than replay window -- skipping to head`);
      return false;
    }

    let raw: string;
    try {
      raw = readFileSync(this.queuePath, "utf8");
    } catch {
      return false; // no queue yet
    }

    let byteOffset = 0; // bytes BEFORE the first event we want to replay
    let positioned = false;
    let replayCount = 0;
    let scannedSeqMax = 0;
    let firstSeq = -1;

    for (const line of raw.split("\n")) {
      if (!line) continue;
      const lineBytes = Buffer.byteLength(line, "utf8") + 1; // +1 for the "\n"
      let event: QueueEvent;
      try {
        event = JSON.parse(line);
      } catch {
        if (!positioned) byteOffset += lineBytes;
        continue;
      }
      if (typeof event.seq === "number") scannedSeqMax = Math.max(scannedSeqMax, event.seq);
      if (firstSeq === -1 && typeof event.seq === "number") firstSeq = event.seq;

      if (!positioned) {
        const eventTs = Date.parse(event.ts);
        const isGap =
          typeof event.seq === "number" &&
          event.seq > cursor.seq &&
          !Number.isNaN(eventTs) &&
          eventTs >= cutoff;
        if (isGap) {
          // Start replay AT this event. lastSeq is the one just before it so
          // poll()'s dedup (seq <= lastSeq) lets this event through.
          this.offset = byteOffset;
          this.lastSeq = cursor.seq;
          positioned = true;
          replayCount++;
        } else {
          byteOffset += lineBytes;
        }
      } else {
        replayCount++;
      }
    }

    // Rotation guard: if the file's lowest seq is already past our cursor, the
    // file we were reading has rotated away -- don't blindly replay a fresh
    // file's whole contents; fall back to head.
    if (firstSeq > cursor.seq + 1) {
      this.log(`Queue seq starts at ${firstSeq} (> cursor ${cursor.seq}) -- rotation since cursor; skipping to head`);
      return false;
    }

    if (!positioned) {
      // No in-window gap. Park at the cursor's logical position so future events
      // emit normally, but don't rewind the byte offset past current EOF.
      return false;
    }

    this.log(
      `Replaying ${replayCount} gap event(s) from seq ${cursor.seq + 1} (cursor ts ${cursor.ts}); ` +
        `offset ${this.offset}, queue head seq ${scannedSeqMax}`
    );
    return true;
  }

  /** One poll cycle: read any bytes appended since `offset`, emit new events. */
  async poll(): Promise<void> {
    if (this.stopped || this.polling) return;
    this.polling = true;
    try {
      let size: number;
      try {
        size = statSync(this.queuePath).size;
      } catch {
        // ENOENT: rotated and the new file hasn't been created yet.
        if (this.offset !== 0) {
          this.log("Queue file gone (rotation) -- re-opening from start");
          this.offset = 0;
          this.lastSeq = 0;
        }
        return;
      }

      if (size < this.offset) {
        // Truncated/rotated underneath us -- new file, read from the top.
        this.log("Queue file shrank (rotation) -- re-opening from start");
        this.offset = 0;
        this.lastSeq = 0;
      }
      if (size === this.offset) return;

      const fd = Bun.file(this.queuePath);
      const chunk = await fd.slice(this.offset, size).text();
      // Only consume complete lines; a partially-written line stays for next poll.
      const lastNewline = chunk.lastIndexOf("\n");
      if (lastNewline === -1) return;
      const complete = chunk.slice(0, lastNewline);
      this.offset += lastNewline + 1;

      for (const line of complete.split("\n")) {
        if (!line.trim()) continue;
        let event: QueueEvent;
        try {
          event = JSON.parse(line);
        } catch {
          this.log(`Skipping malformed queue line: ${line.slice(0, 120)}`);
          continue;
        }
        if (typeof event.seq === "number" && event.seq <= this.lastSeq && event.seq !== 0) {
          // seq reset (rotation race) -- accept and resync.
          if (event.seq < this.lastSeq && event.seq <= 1) {
            this.log(`Seq reset detected (${this.lastSeq} -> ${event.seq})`);
          } else if (event.seq <= this.lastSeq) {
            continue; // duplicate
          }
        }
        this.lastSeq = event.seq;
        if (this.holder) {
          try {
            await this.emit(event);
            // Persist the durable cursor only after a successful emit, so a gap
            // is always replayable up to the last event we actually delivered.
            this.writeCursor(event);
          } catch (e: any) {
            this.log(`Emit failed for seq ${event.seq}: ${e?.message}`);
          }
        }
      }
    } finally {
      this.polling = false;
    }
  }

  // --- Durable cursor ------------------------------------------------------------

  private readCursor(): ConsumerCursor | null {
    try {
      const c = JSON.parse(readFileSync(this.cursorPath, "utf8"));
      if (typeof c.seq === "number" && typeof c.ts === "string") return c;
    } catch {
      // missing or corrupt -- no cursor, fall back to head
    }
    return null;
  }

  /** Persist the last-emitted position. Best-effort: never throws into poll(). */
  private writeCursor(event: QueueEvent): void {
    try {
      const cursor: ConsumerCursor = {
        seq: event.seq,
        ts: event.ts,
        updated_at: new Date().toISOString(),
      };
      writeFileSync(this.cursorPath, JSON.stringify(cursor, null, 2) + "\n");
    } catch {
      // best-effort; worst case a future session falls back to head
    }
  }

  // --- Consumer lock -------------------------------------------------------------

  private readLock(): ConsumerLock | null {
    try {
      const lock = JSON.parse(readFileSync(this.lockPath, "utf8"));
      if (typeof lock.pid === "number" && typeof lock.heartbeat === "string") return lock;
    } catch {
      // missing or corrupt -- treat as free
    }
    return null;
  }

  private writeClaim(): void {
    const claim: ConsumerLock = {
      pid: process.pid,
      sessionStart: this.sessionStart,
      heartbeat: new Date().toISOString(),
    };
    writeFileSync(this.lockPath, JSON.stringify(claim, null, 2) + "\n");
  }

  private isStale(lock: ConsumerLock): boolean {
    const hb = Date.parse(lock.heartbeat);
    if (Number.isNaN(hb)) return true;
    return Date.now() - hb > this.staleMs;
  }

  /**
   * Attempt to take the lock if it's free or stale. Write-with-verify: write
   * our claim, wait, and confirm our pid survived (another contender may have
   * overwritten it in the window).
   */
  async tryAcquireLock(): Promise<boolean> {
    const lock = this.readLock();
    if (lock && lock.pid === process.pid) {
      this.holder = true;
      return true;
    }
    if (lock && !this.isStale(lock)) {
      if (this.holder) this.log("Lost consumer lock -- stopping emission");
      this.holder = false;
      return false;
    }

    // Free or stale: claim it.
    this.writeClaim();
    await Bun.sleep(this.verifyMs);
    const after = this.readLock();
    if (after && after.pid === process.pid) {
      if (!this.holder) this.log(`Acquired consumer lock (pid ${process.pid})`);
      this.holder = true;
      return true;
    }
    this.holder = false;
    this.log("Lock claim lost the race -- standing by");
    return false;
  }

  /** Periodic lock maintenance: holders refresh, non-holders watch for staleness. */
  async lockTick(): Promise<void> {
    if (this.stopped) return;
    if (this.holder) {
      const lock = this.readLock();
      if (!lock || lock.pid !== process.pid) {
        // Someone took it from us (manual intervention or race) -- stand down.
        this.holder = false;
        this.log("Lost consumer lock -- stopping emission");
        return;
      }
      this.writeClaim(); // refresh heartbeat
    } else {
      await this.tryAcquireLock();
    }
  }
}
