/**
 * Daemon integration test -- runs daemon.ts on side port 8799 with a
 * temp queue, fires synthetic webhook POSTs, and verifies filtering,
 * queueing, seq ordering, stats counters, health, and rotation.
 *
 * NEVER binds 8788.
 */
import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PORT = 8799;
const BASE = `http://127.0.0.1:${PORT}`;
const SRC_DIR = join(import.meta.dir, "..");

let dir: string;
let queuePath: string;
let headPath: string;
let statsPath: string;
let daemon: Bun.Subprocess | null = null;

function startDaemon(extraEnv: Record<string, string> = {}): Bun.Subprocess {
  return Bun.spawn(["bun", join(SRC_DIR, "daemon.ts")], {
    env: {
      ...process.env,
      EVENTS_PORT: String(PORT),
      QUEUE_PATH: queuePath,
      EVENTS_STATS_FILE: statsPath,
      ...extraEnv,
    },
    stdout: "inherit",
    stderr: "inherit",
  });
}

async function waitForHealth(timeoutMs = 10_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BASE}/health`);
      if (res.ok) return;
    } catch {
      // not up yet
    }
    await Bun.sleep(100);
  }
  throw new Error("daemon did not become healthy");
}

async function post(payload: unknown): Promise<string> {
  const res = await fetch(BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return res.text();
}

function readQueue(): any[] {
  if (!existsSync(queuePath)) return [];
  return readFileSync(queuePath, "utf8")
    .trimEnd()
    .split("\n")
    .filter(Boolean)
    .map((l) => JSON.parse(l));
}

async function stopDaemon(): Promise<void> {
  if (daemon) {
    daemon.kill();
    await daemon.exited;
    daemon = null;
  }
}

beforeAll(async () => {
  dir = mkdtempSync(join(tmpdir(), "events-daemon-test-"));
  queuePath = join(dir, "queue.jsonl");
  headPath = join(dir, "queue-head.json");
  statsPath = join(dir, "filter-stats.json");
  daemon = startDaemon();
  await waitForHealth();
});

afterAll(async () => {
  await stopDaemon();
  rmSync(dir, { recursive: true, force: true });
});

describe("events daemon", () => {
  test("health endpoint returns ok/seq/uptime", async () => {
    const health = await (await fetch(`${BASE}/health`)).json() as any;
    expect(health.ok).toBe(true);
    expect(health.seq).toBe(0);
    expect(typeof health.uptime).toBe("number");
  });

  test("no-op job_complete is dropped and counted, not queued", async () => {
    const reply = await post({
      event_type: "job_complete",
      job: "sys-pm-loop",
      status: "ok",
      message: "No changes detected",
      source: "plombery",
    });
    expect(reply).toBe("ok (filtered)");
    expect(readQueue()).toHaveLength(0);

    const stats = JSON.parse(readFileSync(statsPath, "utf8"));
    expect(stats.dropped).toBe(1);
    expect(stats.delivered).toBe(0);
    expect(stats.dropped_by_job["sys-pm-loop"]).toBe(1);
  });

  test("meaningful job_complete, alert, and run_skill are queued in seq order", async () => {
    expect(
      await post({
        event_type: "job_complete",
        job: "o365-email",
        status: "ok",
        message: "Synced 12 new emails",
        source: "plombery",
      })
    ).toBe("ok");
    expect(
      await post({
        event_type: "alert",
        severity: "critical",
        message: "Disk usage at 95% on host",
        source: "monitoring",
      })
    ).toBe("ok");
    expect(
      await post({
        event_type: "run_skill",
        skill: "morning-brief",
        message: "Skill run requested: morning-brief",
        source: "plombery",
      })
    ).toBe("ok");

    const queue = readQueue();
    expect(queue).toHaveLength(3);
    expect(queue.map((e) => e.seq)).toEqual([1, 2, 3]);
    expect(queue.every((e) => typeof e.ts === "string" && !Number.isNaN(Date.parse(e.ts)))).toBe(true);

    expect(queue[0].meta.event_type).toBe("job_complete");
    expect(queue[0].meta.job).toBe("o365-email");
    expect(queue[0].content).toBe("Synced 12 new emails");
    expect(queue[1].meta.event_type).toBe("alert");
    expect(queue[1].meta.severity).toBe("critical");
    expect(queue[2].meta.event_type).toBe("run_skill");
    expect(queue[2].meta.skill).toBe("morning-brief");

    const head = JSON.parse(readFileSync(headPath, "utf8"));
    expect(head.seq).toBe(3);

    const stats = JSON.parse(readFileSync(statsPath, "utf8"));
    expect(stats.delivered).toBe(3);
    expect(stats.dropped).toBe(1);

    const health = await (await fetch(`${BASE}/health`)).json() as any;
    expect(health.seq).toBe(3);
  });

  test("plain-text body is treated as a webhook and queued", async () => {
    const res = await fetch(`${BASE}/github`, { method: "POST", body: "push to main" });
    expect(await res.text()).toBe("ok");
    const queue = readQueue();
    const last = queue[queue.length - 1];
    expect(last.seq).toBe(4);
    expect(last.meta.event_type).toBe("webhook");
    expect(last.meta.source).toBe("github");
    expect(last.content).toBe("push to main");
  });

  test("restart restores seq from queue-head.json (monotonic across restarts)", async () => {
    await stopDaemon();
    daemon = startDaemon();
    await waitForHealth();
    const health = await (await fetch(`${BASE}/health`)).json() as any;
    expect(health.seq).toBe(4);

    expect(await post({ event_type: "alert", message: "after restart" })).toBe("ok");
    const queue = readQueue();
    expect(queue[queue.length - 1].seq).toBe(5);
  });

  test("queue rotates past size cap and seq resets", async () => {
    // Restart with a tiny cap; the existing queue (5 events) is over it.
    await stopDaemon();
    daemon = startDaemon({ QUEUE_MAX_BYTES: "200" });
    await waitForHealth();

    expect(await post({ event_type: "alert", message: "triggers rotation" })).toBe("ok");

    const rotated = readdirSync(dir).filter((f) => /^queue-\d{4}-\d{2}-\d{2}/.test(f) && f !== "queue-head.json");
    expect(rotated.length).toBe(1);

    const queue = readQueue();
    expect(queue).toHaveLength(1);
    expect(queue[0].seq).toBe(1); // reset
    expect(queue[0].content).toBe("triggers rotation");

    const head = JSON.parse(readFileSync(headPath, "utf8"));
    expect(head.seq).toBe(1);

    // Rotated file holds the old events, ending at seq 5.
    const old = readFileSync(join(dir, rotated[0]!), "utf8").trimEnd().split("\n").map((l) => JSON.parse(l));
    expect(old[old.length - 1].seq).toBe(5);
  });
});
