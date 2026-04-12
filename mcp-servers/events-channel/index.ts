#!/usr/bin/env bun
/**
 * Edwin Events Channel -- pushes job events, alerts, and webhooks into Claude Code sessions.
 *
 * One-way channel: receives HTTP POSTs from Plombery, the job handler, monitoring
 * scripts, or any system that can send an HTTP request. Forwards them into the
 * active Claude Code session as <channel source="events" ...> tags.
 *
 * Following the Anthropic Channels Reference:
 * https://code.claude.com/docs/en/channels-reference
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

// --- Configuration -----------------------------------------------------------

const PORT = parseInt(process.env.EVENTS_PORT || "8790", 10);

// --- Logging (stderr so it doesn't pollute MCP stdio) ------------------------

function log(msg: string): void {
  process.stderr.write(`[events-channel] ${msg}\n`);
}

// --- MCP Server Setup --------------------------------------------------------

const mcp = new Server(
  { name: "events", version: "1.0.0" },
  {
    capabilities: {
      experimental: { "claude/channel": {} },
    },
    instructions: [
      'Events from external systems arrive as <channel source="events" ...>.',
      "They are one-way: read them and act, no reply expected.",
      "Each event has an event_type attribute (e.g. job_complete, run_skill, alert, webhook).",
      "For job_complete events: check the status and log/report as needed.",
      "For run_skill events: read the skill attribute to get the skill name, then spawn a background subagent to execute it. The subagent should read and follow ~/Edwin/skills/{skill}/SKILL.md. When the subagent returns, relay any items needing the user's attention via iMessage.",
      "For nightwatch_heartbeat events: check if a nightwatch task subagent is currently running. If not, read the plan file at ~/Edwin/data/nightwatch/YYYY-MM-DD-plan.md, find the next uncompleted task, and spawn a subagent to execute it. Check the time first -- if after 3:30 AM ET, don't spawn, just log wind-down.",
      "For alert events: assess severity and notify the user if critical.",
      "For webhook events: process based on the source and payload.",
    ].join(" "),
  }
);

// --- Connect to Claude Code over stdio ---------------------------------------

await mcp.connect(new StdioServerTransport());
log("MCP connected");

// --- HTTP Server: receives events and pushes to session ----------------------

Bun.serve({
  port: PORT,
  hostname: "127.0.0.1",
  async fetch(req) {
    const url = new URL(req.url);

    // Health check
    if (req.method === "GET" && url.pathname === "/health") {
      return new Response(JSON.stringify({ status: "ok", port: PORT }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    if (req.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    try {
      const body = await req.text();
      let content: string;
      let meta: Record<string, string> = {};

      // Try to parse as JSON for structured events
      try {
        const json = JSON.parse(body);
        content = json.message || json.content || json.text || body;
        meta = {
          event_type: json.event_type || json.type || json.event || "unknown",
          source: json.source || url.pathname.replace(/^\//, "") || "unknown",
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
          source: url.pathname.replace(/^\//, "") || "unknown",
        };
      }

      await mcp.notification({
        method: "notifications/claude/channel",
        params: { content, meta },
      });

      log(`Event pushed: ${meta.event_type} from ${meta.source}`);
      return new Response("ok");
    } catch (e: any) {
      log(`Error: ${e.message}`);
      return new Response(`Error: ${e.message}`, { status: 500 });
    }
  },
});

log(`Listening on localhost:${PORT}`);