#!/usr/bin/env bun
/**
 * Edwin Events Channel -- pushes job events, alerts, and webhooks into Claude Code sessions.
 *
 * One-way channel: the events daemon (daemon.ts, launchd-managed) owns port
 * 8788, receives HTTP POSTs from Plombery, the job handler, monitoring
 * scripts, or any system that can send an HTTP request, filters no-ops, and
 * appends deliverable events to data/events-channel/queue.jsonl. This MCP
 * server is the session-side READER: it tails that queue and forwards events
 * into the active Claude Code session as <channel source="events" ...> tags.
 *
 * It binds NO ports. Every session may run its own copy safely; a consumer
 * lock (tailer.ts) ensures exactly one session receives the feed, with
 * automatic failover within ~2 minutes if that session dies. This is the fix
 * for the class of bug where per-session port contention causes long,
 * silent outages in the events feed.
 *
 * Following the Anthropic Channels Reference:
 * https://code.claude.com/docs/en/channels-reference
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { QueueTailer } from "./tailer.ts";

// --- Configuration -----------------------------------------------------------

const EDWIN_HOME = process.env.EDWIN_HOME || `${process.env.HOME}/Edwin`;
const QUEUE_PATH = process.env.QUEUE_PATH || `${EDWIN_HOME}/data/events-channel/queue.jsonl`;

// --- Logging (stderr so it doesn't pollute MCP stdio) ------------------------

function log(msg: string): void {
  process.stderr.write(`[events-channel] ${msg}\n`);
}

// --- MCP Server Setup --------------------------------------------------------

const mcp = new Server(
  { name: "events", version: "2.0.0" },
  {
    capabilities: {
      experimental: { "claude/channel": {} },
    },
    instructions: [
      'Events from external systems arrive as <channel source="events" ...>.',
      "They are one-way: read them and act, no reply expected.",
      "Each event has an event_type attribute (e.g. job_complete, run_skill, alert, webhook).",
      "Routine no-op job completions are filtered server-side and never reach you -- any job_complete you see is an error or did meaningful work, so it deserves attention.",
      "For job_complete events: check the status and log/report as needed.",
      "For run_skill events: run `~/Edwin/tools/dispatch/dispatch run_skill --skill NAME` (NAME from the event's skill attribute) and execute the returned JSON instruction verbatim -- do not re-derive the decision. Ack outcomes with `dispatch ack`. When the subagent returns, relay any items needing the user's attention via iMessage.",
      "For nightwatch_heartbeat events: run `~/Edwin/tools/dispatch/dispatch nightwatch_heartbeat` and execute the returned JSON instruction verbatim (noop, log_winddown, spawn_planner, spawn_replanner, spawn_tasks, or surface_to_user) -- do not re-derive the decision. Ack every dispatch_id: spawned after spawning, completed/failed when it returns.",
      "For alert events: assess severity and notify the user if critical.",
      "For webhook events: process based on the source and payload.",
    ].join(" "),
  }
);

// --- Connect to Claude Code over stdio ---------------------------------------

await mcp.connect(new StdioServerTransport());
log("MCP connected");

// --- Queue reader: tails the daemon's queue and pushes to session -------------
//
// Starts at the CURRENT head -- a fresh session never replays old events.
// Only the consumer-lock holder emits; everyone else tails silently and
// stands by for failover (see tailer.ts for the lock protocol).

const tailer = new QueueTailer({
  queuePath: QUEUE_PATH,
  log,
  emit: async ({ content, meta }) => {
    await mcp.notification({
      method: "notifications/claude/channel",
      params: { content, meta },
    });
    log(`Event pushed: ${meta.event_type} from ${meta.source}`);
  },
});

await tailer.start();
log(`Tailing ${QUEUE_PATH} (lock holder: ${tailer.isHolder})`);
