/**
 * Edwin Events Channel -- shared event parsing + no-op filter logic.
 *
 * Used by daemon.ts (the permanent port-8788 listener). The filter decides
 * which events are worth the orchestrator's context window. This code was
 * moved verbatim from index.ts when the listener/reader split happened;
 * keep the signatures and filter-stats.json shape identical.
 */

// --- Event filtering -----------------------------------------------------------
// The orchestrator session's context window is the scarcest resource in the
// architecture. Routine no-op job_complete events (~300/day: "Published 0,
// skipped 574" every 5 minutes, etc.) used to be pushed straight into it.
// Filter them here. Always delivered: run_skill, nightwatch_heartbeat, alerts,
// webhooks, anything with status != ok, and job_complete events that did
// meaningful work. Dropped (but counted): successful no-op completions.
// Fail open: anything unrecognized is delivered.

// Per-job no-op signatures (matched against event content, job_complete + ok only).
export const NOOP_BY_JOB: Record<string, RegExp> = {
  "sys-workspace-publish": /Published 0, skipped \d+/i,
  "sys-obsidian-watcher": /No changes to sync/i,
  // Captures and small slice ticks are routine housekeeping during active
  // sessions (~every 10-15 min); they never require orchestrator action.
  // Large slice bursts (4+) still deliver -- that's a real backlog event.
  "sys-session-watcher": /No capture needed|Capture complete|Capture triggered|No active session found/i,
  "sys-session-slicer": /created [0-3] new slices/i,
  "sys-pm-loop": /No changes detected/i,
  "sys-pm-wake": /No deferred items found|No items ready to wake/i,
  // Snapshot lands in data/ambient/ every 30 min; nothing for the orchestrator to do.
  "sys-ambient-poll": /Snapshot|Limitless: \d+ conversations/i,
  // The real signal is the separate nightwatch_heartbeat event, which is always delivered.
  "sys-nightwatch-heartbeat": /Heartbeat sent|Nightwatch not active|No nightwatch state file|stop time reached|Could not read nightwatch state/i,
};

// Generic no-op signatures (any job).
export const NOOP_GENERIC: RegExp[] = [
  /Sync complete\s*[—–-]+\s*0 total (items|sessions)/i, // connector ran, nothing new
  /Skill event fired:/i, // skill-* trigger echo -- the run_skill event itself is delivered
  /^OK\s*$/, // bare OK, no information
  /Another sync is already running\s*[—–-]+\s*exiting/i, // flock skip -- by design, nothing happened
];

export function isNoopJobComplete(meta: Record<string, string>, content: string): boolean {
  if (meta.event_type !== "job_complete") return false;
  if (meta.status !== "ok") return false; // errors always delivered
  const job = meta.job || "";
  const perJob = NOOP_BY_JOB[job];
  if (perJob && perJob.test(content)) return true;
  return NOOP_GENERIC.some((re) => re.test(content));
}

// --- Payload parsing -----------------------------------------------------------
// Same contract as the original index.ts HTTP handler: JSON bodies become
// structured events, anything else is a plain-text webhook.

export interface ParsedEvent {
  content: string;
  meta: Record<string, string>;
}

export function parseEventBody(body: string, pathname: string): ParsedEvent {
  let content: string;
  let meta: Record<string, string> = {};

  // Try to parse as JSON for structured events
  try {
    const json = JSON.parse(body);
    content = json.message || json.content || json.text || body;
    meta = {
      event_type: json.event_type || json.type || json.event || "unknown",
      source: json.source || pathname.replace(/^\//, "") || "unknown",
      ...(json.job ? { job: json.job } : {}),
      ...(json.status ? { status: json.status } : {}),
      ...(json.severity ? { severity: json.severity } : {}),
      ...(json.pipeline_id ? { pipeline_id: json.pipeline_id } : {}),
      ...(json.skill ? { skill: json.skill } : {}),
    };
  } catch {
    // Plain text
    content = body;
    meta = {
      event_type: "webhook",
      source: pathname.replace(/^\//, "") || "unknown",
    };
  }

  return { content, meta };
}

// --- Filter stats (so the watchdog/ops pages can see what's being suppressed) --
// Identical shape and lifecycle to the original index.ts: counters reset when
// the owning process starts, file rewritten after every event.

export interface FilterStats {
  started_at: string;
  delivered: number;
  dropped: number;
  dropped_by_job: Record<string, number>;
}

export function createStats(): FilterStats {
  return {
    started_at: new Date().toISOString(),
    delivered: 0,
    dropped: 0,
    dropped_by_job: {},
  };
}

export async function writeStats(statsFile: string, stats: FilterStats): Promise<void> {
  try {
    await Bun.write(statsFile, JSON.stringify(stats, null, 2) + "\n");
  } catch {
    // stats are best-effort; never fail event handling over them
  }
}
