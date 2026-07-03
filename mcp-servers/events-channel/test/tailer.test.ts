/**
 * Tailer + consumer-lock unit tests. Exercises the reader's tail/lock logic
 * (tailer.ts) directly with a temp queue and compressed timings -- this is
 * the same code index.ts wires to mcp.notification.
 *
 * Covers: fresh start skips history; lock acquisition; heartbeat refresh;
 * takeover after stale heartbeat; non-holder silence while a fresh foreign
 * lock exists; rotation handling.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { appendFileSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { QueueTailer, type QueueEvent } from "../tailer.ts";

const FAST = { pollMs: 50, heartbeatMs: 100, staleMs: 300, verifyMs: 50 };

interface Ctx {
  dir: string;
  queuePath: string;
  headPath: string;
  lockPath: string;
  cursorPath: string;
  emitted: QueueEvent[];
  tailer?: QueueTailer;
}

const cleanups: (() => void)[] = [];

function makeCtx(): Ctx {
  const dir = mkdtempSync(join(tmpdir(), "events-tailer-test-"));
  const ctx: Ctx = {
    dir,
    queuePath: join(dir, "queue.jsonl"),
    headPath: join(dir, "queue-head.json"),
    lockPath: join(dir, ".consumer-lock.json"),
    cursorPath: join(dir, ".consumer-cursor.json"),
    emitted: [],
  };
  cleanups.push(() => {
    ctx.tailer?.stop();
    rmSync(dir, { recursive: true, force: true });
  });
  return ctx;
}

function makeTailer(ctx: Ctx): QueueTailer {
  ctx.tailer = new QueueTailer({
    queuePath: ctx.queuePath,
    emit: (e) => {
      ctx.emitted.push(e);
    },
    ...FAST,
  });
  return ctx.tailer;
}

function writeEvent(ctx: Ctx, seq: number, content: string, ts?: string): void {
  const eventTs = ts ?? new Date().toISOString();
  appendFileSync(
    ctx.queuePath,
    JSON.stringify({ seq, ts: eventTs, content, meta: { event_type: "alert", source: "test" } }) + "\n"
  );
  writeFileSync(ctx.headPath, JSON.stringify({ seq, updated_at: new Date().toISOString() }) + "\n");
}

function writeCursor(ctx: Ctx, seq: number, ts?: string): void {
  const cursorTs = ts ?? new Date().toISOString();
  writeFileSync(
    ctx.cursorPath,
    JSON.stringify({ seq, ts: cursorTs, updated_at: new Date().toISOString() }) + "\n"
  );
}

const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

describe("queue tailer", () => {
  test("fresh start skips history, emits only new events", async () => {
    const ctx = makeCtx();
    writeEvent(ctx, 1, "old one");
    writeEvent(ctx, 2, "old two");
    writeEvent(ctx, 3, "old three");

    const tailer = makeTailer(ctx);
    await tailer.start();
    expect(tailer.currentSeq).toBe(3);

    writeEvent(ctx, 4, "new event");
    await Bun.sleep(200);

    expect(ctx.emitted.map((e) => e.seq)).toEqual([4]);
    expect(ctx.emitted[0]!.content).toBe("new event");
  });

  test("acquires the consumer lock when free", async () => {
    const ctx = makeCtx();
    const tailer = makeTailer(ctx);
    await tailer.start();

    expect(tailer.isHolder).toBe(true);
    const lock = JSON.parse(readFileSync(ctx.lockPath, "utf8"));
    expect(lock.pid).toBe(process.pid);
    expect(typeof lock.sessionStart).toBe("string");
    expect(typeof lock.heartbeat).toBe("string");
  });

  test("holder refreshes its heartbeat", async () => {
    const ctx = makeCtx();
    const tailer = makeTailer(ctx);
    await tailer.start();

    const hb1 = JSON.parse(readFileSync(ctx.lockPath, "utf8")).heartbeat;
    await Bun.sleep(FAST.heartbeatMs * 2 + 50);
    const hb2 = JSON.parse(readFileSync(ctx.lockPath, "utf8")).heartbeat;
    expect(Date.parse(hb2)).toBeGreaterThan(Date.parse(hb1));
    expect(tailer.isHolder).toBe(true);
  });

  test("does not emit while a fresh foreign lock exists, takes over once stale", async () => {
    const ctx = makeCtx();
    // Fake lock from a "live" foreign session (heartbeat = now).
    writeFileSync(
      ctx.lockPath,
      JSON.stringify({ pid: 4999999, sessionStart: new Date().toISOString(), heartbeat: new Date().toISOString() }) + "\n"
    );

    const tailer = makeTailer(ctx);
    await tailer.start();
    expect(tailer.isHolder).toBe(false);

    // Event arrives while foreign session holds the lock -- must stay silent.
    writeEvent(ctx, 1, "not ours");
    await Bun.sleep(150);
    expect(ctx.emitted).toHaveLength(0);

    // Foreign session dies (heartbeat goes stale). Takeover within ~staleMs + tick.
    await Bun.sleep(FAST.staleMs + FAST.heartbeatMs * 2 + FAST.verifyMs * 2);
    expect(tailer.isHolder).toBe(true);
    const lock = JSON.parse(readFileSync(ctx.lockPath, "utf8"));
    expect(lock.pid).toBe(process.pid);

    // Now it emits.
    writeEvent(ctx, 2, "ours now");
    await Bun.sleep(200);
    expect(ctx.emitted.map((e) => e.seq)).toEqual([2]);
  });

  test("takes over immediately when the existing lock is already stale", async () => {
    const ctx = makeCtx();
    const old = new Date(Date.now() - 10 * 60 * 1000).toISOString();
    writeFileSync(ctx.lockPath, JSON.stringify({ pid: 4999999, sessionStart: old, heartbeat: old }) + "\n");

    const tailer = makeTailer(ctx);
    await tailer.start();
    expect(tailer.isHolder).toBe(true);
    expect(JSON.parse(readFileSync(ctx.lockPath, "utf8")).pid).toBe(process.pid);
  });

  test("holder stands down when another process overwrites the lock", async () => {
    const ctx = makeCtx();
    const tailer = makeTailer(ctx);
    await tailer.start();
    expect(tailer.isHolder).toBe(true);

    // Simulate a competing claim landing on disk.
    writeFileSync(
      ctx.lockPath,
      JSON.stringify({ pid: 4999998, sessionStart: new Date().toISOString(), heartbeat: new Date().toISOString() }) + "\n"
    );
    await Bun.sleep(FAST.heartbeatMs * 2 + 50);
    expect(tailer.isHolder).toBe(false);

    writeEvent(ctx, 1, "should not emit");
    await Bun.sleep(150);
    expect(ctx.emitted).toHaveLength(0);
  });

  test("handles rotation: re-opens on shrink/ENOENT and accepts seq reset", async () => {
    const ctx = makeCtx();
    writeEvent(ctx, 7, "pre-existing");
    const tailer = makeTailer(ctx);
    await tailer.start();

    writeEvent(ctx, 8, "before rotation");
    await Bun.sleep(150);
    expect(ctx.emitted.map((e) => e.seq)).toEqual([8]);

    // Daemon rotates: old file renamed away, new file starts at seq 1.
    renameSync(ctx.queuePath, join(ctx.dir, "queue-2026-06-12.jsonl"));
    await Bun.sleep(150); // tailer sees ENOENT, resets
    writeEvent(ctx, 1, "after rotation");
    await Bun.sleep(200);

    expect(ctx.emitted.map((e) => e.seq)).toEqual([8, 1]);
    expect(ctx.emitted[1]!.content).toBe("after rotation");
  });
});

describe("durable consumer cursor (bounded replay)", () => {
  test("no cursor: behaves exactly like skip-to-head (backward compatible)", async () => {
    const ctx = makeCtx();
    writeEvent(ctx, 1, "old one");
    writeEvent(ctx, 2, "old two");
    const tailer = makeTailer(ctx);
    await tailer.start();
    expect(tailer.currentSeq).toBe(2);

    writeEvent(ctx, 3, "new");
    await Bun.sleep(200);
    expect(ctx.emitted.map((e) => e.seq)).toEqual([3]); // history skipped
  });

  test("recent cursor: replays the gap that arrived while no session was alive", async () => {
    const ctx = makeCtx();
    // Consumer last delivered seq 2; then events 3,4 arrived while it was dead.
    writeEvent(ctx, 1, "pre");
    writeEvent(ctx, 2, "last delivered");
    writeEvent(ctx, 3, "gap a");
    writeEvent(ctx, 4, "gap b");
    writeCursor(ctx, 2, minutesAgo(5));

    const tailer = makeTailer(ctx);
    await tailer.start();
    await Bun.sleep(200);

    // 3 and 4 are replayed; 1 and 2 are not.
    expect(ctx.emitted.map((e) => e.seq)).toEqual([3, 4]);
    expect(ctx.emitted.map((e) => e.content)).toEqual(["gap a", "gap b"]);

    // And new events keep flowing after the replay.
    writeEvent(ctx, 5, "live");
    await Bun.sleep(200);
    expect(ctx.emitted.map((e) => e.seq)).toEqual([3, 4, 5]);
  });

  test("cursor at head: nothing to replay, only new events emit", async () => {
    const ctx = makeCtx();
    writeEvent(ctx, 1, "a");
    writeEvent(ctx, 2, "b");
    writeCursor(ctx, 2, minutesAgo(1));

    const tailer = makeTailer(ctx);
    await tailer.start();
    await Bun.sleep(150);
    expect(ctx.emitted).toHaveLength(0); // no gap past cursor

    writeEvent(ctx, 3, "c");
    await Bun.sleep(200);
    expect(ctx.emitted.map((e) => e.seq)).toEqual([3]);
  });

  test("stale cursor (older than 2h window): falls back to head, no flood", async () => {
    const ctx = makeCtx();
    writeEvent(ctx, 1, "ancient", minutesAgo(200));
    writeEvent(ctx, 2, "ancient2", minutesAgo(190));
    writeCursor(ctx, 1, minutesAgo(200)); // cursor itself is 200 min old

    const tailer = makeTailer(ctx);
    await tailer.start();
    await Bun.sleep(200);
    expect(ctx.emitted).toHaveLength(0); // did not replay ancient gap

    writeEvent(ctx, 3, "fresh");
    await Bun.sleep(200);
    expect(ctx.emitted.map((e) => e.seq)).toEqual([3]);
  });

  test("bounded replay: only in-window gap events replay, older ones skipped", async () => {
    const ctx = makeCtx();
    // Cursor is recent (10 min ago) but some gap events are >2h old.
    writeEvent(ctx, 1, "old gap", minutesAgo(200)); // outside window
    writeEvent(ctx, 2, "recent gap", minutesAgo(10)); // inside window
    writeEvent(ctx, 3, "recent gap 2", minutesAgo(5));
    writeCursor(ctx, 0, minutesAgo(10));

    const tailer = makeTailer(ctx);
    await tailer.start();
    await Bun.sleep(200);

    // seq 1 is out-of-window so replay starts at seq 2.
    expect(ctx.emitted.map((e) => e.seq)).toEqual([2, 3]);
  });

  test("holder persists the cursor as it emits", async () => {
    const ctx = makeCtx();
    const tailer = makeTailer(ctx);
    await tailer.start();

    writeEvent(ctx, 1, "live one");
    await Bun.sleep(200);
    const cur = JSON.parse(readFileSync(ctx.cursorPath, "utf8"));
    expect(cur.seq).toBe(1);
    expect(typeof cur.ts).toBe("string");
    expect(typeof cur.updated_at).toBe("string");
  });

  test("replayMaxMs=0 disables replay (legacy behavior)", async () => {
    const ctx = makeCtx();
    writeEvent(ctx, 1, "a");
    writeEvent(ctx, 2, "b");
    writeCursor(ctx, 0, minutesAgo(1));

    ctx.tailer = new QueueTailer({
      queuePath: ctx.queuePath,
      emit: (e) => {
        ctx.emitted.push(e);
      },
      ...FAST,
      replayMaxMs: 0,
    });
    await ctx.tailer.start();
    await Bun.sleep(150);
    expect(ctx.emitted).toHaveLength(0); // no replay despite cursor at 0

    writeEvent(ctx, 3, "c");
    await Bun.sleep(200);
    expect(ctx.emitted.map((e) => e.seq)).toEqual([3]);
  });
});
