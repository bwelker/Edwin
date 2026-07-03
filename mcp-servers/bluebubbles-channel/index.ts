#!/usr/bin/env bun
/**
 * BlueBubbles Channel Plugin for Claude Code
 *
 * Two-way iMessage bridge via BlueBubbles REST API.
 * Receives inbound messages via BB webhooks, sends replies via BB Private API.
 * Runs as an MCP server spawned by Claude Code.
 *
 * Required environment variables:
 *   BB_URL            - BlueBubbles server URL (e.g. http://192.168.1.100:1234)
 *   BB_PASSWORD       - BlueBubbles server password
 *   ALLOWED_SENDERS   - Comma-separated E.164 phone numbers (e.g. +15551234567)
 *   OWNER_PHONE       - Your phone number in E.164 format (for permission relay)
 *   OWNER_NAME        - Your name (used in sender display)
 *
 * Optional environment variables:
 *   BB_FALLBACK_URL   - Secondary BlueBubbles URL to try if the primary is
 *                       unreachable (e.g. a stable LAN address when the
 *                       primary is a tunnel URL that can rotate). Defaults
 *                       to BB_URL (no fallback).
 *   BB_MAX_MESSAGE_CHARS - Chunk outbound messages above this length
 *                       (default: 2000). Some transports drop long messages.
 *   BB_DELIVERY_LOG   - Path to a JSONL delivery log (default:
 *                       $EDWIN_HOME/data/bluebubbles/delivery-log.jsonl)
 *   EDWIN_HOME        - Base data directory (default: ~/Edwin)
 *   WEBHOOK_PORT      - Port for the webhook listener (default: 18800)
 *   WEBHOOK_HOST      - LAN IP visible to the BlueBubbles server (default: 0.0.0.0)
 *   SENDER_MAP        - JSON mapping of phone numbers to display names
 *                       e.g. '{ "+15551234567": "Alice", "+15559876543": "Bob" }'
 */
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";
import { appendFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

// --- Configuration -----------------------------------------------------------

const BB_PRIMARY_URL = process.env.BB_URL;
const BB_PASSWORD = process.env.BB_PASSWORD;
if (!BB_PRIMARY_URL || !BB_PASSWORD) {
  process.stderr.write(
    "[bluebubbles-channel] ERROR: BB_URL and BB_PASSWORD environment variables are required.\n"
  );
  process.exit(1);
}
// Optional secondary URL -- useful when the primary is a tunnel that can
// rotate/die (e.g. cloudflared) and there's a stable LAN address as backup.
const BB_FALLBACK_URL = process.env.BB_FALLBACK_URL || BB_PRIMARY_URL;
// Long messages drop silently past a certain size on some transports -- chunk above this
const MAX_MESSAGE_CHARS = parseInt(process.env.BB_MAX_MESSAGE_CHARS || "2000", 10);
const CHUNK_SEND_DELAY_MS = 750;
// Delivery verification: bounded polling of message status after send
const VERIFY_DELAYS_MS = [1000, 2000, 2000];
const CONNECT_TIMEOUT_MS = 5000;
const REQUEST_TIMEOUT_MS = 15000;
const EDWIN_HOME = process.env.EDWIN_HOME || `${process.env.HOME}/Edwin`;
const DELIVERY_LOG = process.env.BB_DELIVERY_LOG || `${EDWIN_HOME}/data/bluebubbles/delivery-log.jsonl`;
const WEBHOOK_PORT = parseInt(process.env.WEBHOOK_PORT || "18800", 10);
// Host LAN IP visible to the BlueBubbles server
const WEBHOOK_HOST = process.env.WEBHOOK_HOST || "0.0.0.0";

// Sender allowlist -- E.164 strings with + prefix
const ALLOWED_SENDERS = (process.env.ALLOWED_SENDERS || "")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);

if (ALLOWED_SENDERS.length === 0) {
  process.stderr.write(
    "[bluebubbles-channel] WARNING: No ALLOWED_SENDERS configured. All inbound messages will be ignored.\n"
  );
}

// Owner phone number for permission relay and sender identification
const OWNER_PHONE = process.env.OWNER_PHONE || "";
const OWNER_NAME = process.env.OWNER_NAME || "Owner";

// Optional sender display name map: { "+15551234567": "Alice" }
let senderMap: Record<string, string> = {};
if (process.env.SENDER_MAP) {
  try {
    senderMap = JSON.parse(process.env.SENDER_MAP);
  } catch {
    process.stderr.write(
      "[bluebubbles-channel] WARNING: SENDER_MAP is not valid JSON, ignoring.\n"
    );
  }
}
// Always include owner in the sender map
if (OWNER_PHONE && OWNER_NAME) {
  senderMap[OWNER_PHONE] = OWNER_NAME;
}

// --- Transport Resolution ------------------------------------------------------
// The primary URL can die silently (e.g. tunnel rotation). Probe the
// primary, fall back to the secondary URL, cache whichever worked for the
// session, and invalidate the cache on any connection-level failure so the
// next call re-resolves.

let activeBase: string | null = null;

class TransportUnreachableError extends Error {}

const bbApi = (base: string, path: string) =>
  `${base}${path}${path.includes("?") ? "&" : "?"}password=${BB_PASSWORD}`;

async function probeBase(base: string): Promise<boolean> {
  try {
    const res = await fetch(bbApi(base, "/api/v1/ping"), {
      signal: AbortSignal.timeout(CONNECT_TIMEOUT_MS),
    });
    const json = (await res.json()) as { status: number };
    return json.status === 200;
  } catch {
    return false;
  }
}

async function resolveTransport(): Promise<string> {
  if (activeBase) return activeBase;
  const candidates =
    BB_PRIMARY_URL === BB_FALLBACK_URL
      ? [BB_PRIMARY_URL]
      : [BB_PRIMARY_URL, BB_FALLBACK_URL];
  for (const base of candidates) {
    if (await probeBase(base)) {
      const note =
        base !== BB_PRIMARY_URL ? " (fallback -- primary unreachable)" : "";
      log(`Transport resolved: ${base}${note}`);
      activeBase = base;
      return base;
    }
  }
  throw new TransportUnreachableError(
    `BlueBubbles unreachable on primary (${BB_PRIMARY_URL})` +
      (BB_FALLBACK_URL !== BB_PRIMARY_URL
        ? ` and fallback (${BB_FALLBACK_URL})`
        : "")
  );
}

// --- GUID Dedup Cache --------------------------------------------------------

const seenGuids = new Map<string, number>();
const DEDUP_TTL_MS = 60_000;

function isDuplicate(guid: string): boolean {
  const now = Date.now();
  if (seenGuids.size > 500) {
    for (const [k, v] of seenGuids) {
      if (now - v > DEDUP_TTL_MS) seenGuids.delete(k);
    }
  }
  if (seenGuids.has(guid)) return true;
  seenGuids.set(guid, now);
  return false;
}

// --- BlueBubbles API Helpers -------------------------------------------------

async function bbFetch(path: string, options?: RequestInit): Promise<Response> {
  const base = await resolveTransport();
  try {
    return await fetch(bbApi(base, path), {
      ...options,
      headers: { "Content-Type": "application/json", ...options?.headers },
      signal: options?.signal ?? AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (e) {
    // Connection-level failure: transport may have died mid-session.
    // Invalidate the cache so the next call re-resolves. Do NOT auto-retry
    // here -- message senders must handle ambiguity themselves.
    activeBase = null;
    throw e;
  }
}

interface SendResult {
  ok: boolean;
  guid?: string;
  error?: string;
  // true when the request threw mid-flight: the message MAY have gone out.
  // false when the server explicitly rejected or was unreachable pre-send.
  ambiguous?: boolean;
}

async function sendMessage(chatGuid: string, text: string): Promise<SendResult> {
  const tempGuid = `temp-${crypto.randomUUID()}`;
  try {
    const res = await bbFetch("/api/v1/message/text", {
      method: "POST",
      body: JSON.stringify({
        chatGuid,
        tempGuid,
        message: text,
        method: "private-api",
      }),
    });
    const json = (await res.json()) as {
      status: number;
      message: string;
      data?: { guid?: string };
    };
    if (json.status === 200) return { ok: true, guid: json.data?.guid };
    return { ok: false, error: json.message };
  } catch (e: any) {
    if (e instanceof TransportUnreachableError) {
      return { ok: false, error: e.message, ambiguous: false };
    }
    return { ok: false, error: e.message, ambiguous: true };
  }
}

// --- Delivery Verification -----------------------------------------------------

interface MessageStatus {
  found: boolean;
  errorCode?: number;
  dateDelivered?: number | null;
  isDelivered?: boolean;
}

// null = the lookup itself failed (transport error), NOT "message missing"
async function getMessageStatus(guid: string): Promise<MessageStatus | null> {
  try {
    const res = await bbFetch(`/api/v1/message/${encodeURIComponent(guid)}`);
    const json = (await res.json()) as { status: number; data?: any };
    if (json.status === 200 && json.data) {
      return {
        found: true,
        errorCode: json.data.error,
        dateDelivered: json.data.dateDelivered,
        isDelivered: json.data.isDelivered,
      };
    }
    if (json.status === 404) return { found: false };
    return null;
  } catch {
    return null;
  }
}

// After an ambiguous send failure, check whether the message actually landed
// on the server. ok=false means the lookup itself failed (still ambiguous).
async function findSentMessage(
  chatGuid: string,
  text: string,
  sinceMs: number
): Promise<{ ok: boolean; guid: string | null }> {
  try {
    const res = await bbFetch("/api/v1/message/query", {
      method: "POST",
      body: JSON.stringify({ chatGuid, limit: 10, sort: "DESC" }),
    });
    const json = (await res.json()) as { status: number; data?: any[] };
    if (json.status !== 200) return { ok: false, guid: null };
    for (const m of json.data || []) {
      if (m.isFromMe && m.text === text && m.dateCreated >= sinceMs - 5000) {
        return { ok: true, guid: m.guid };
      }
    }
    return { ok: true, guid: null };
  } catch {
    return { ok: false, guid: null };
  }
}

type Verification =
  | { state: "delivered"; deliveredAt: number }
  | { state: "accepted" } // on server, error 0, no delivery receipt yet
  | { state: "send_error"; code: number }
  | { state: "not_found" }
  | { state: "unverifiable" }; // status checks themselves failed

async function verifyDelivery(guid: string): Promise<Verification> {
  let last: Verification = { state: "unverifiable" };
  for (const delay of VERIFY_DELAYS_MS) {
    await Bun.sleep(delay);
    const st = await getMessageStatus(guid);
    if (st === null) {
      last = { state: "unverifiable" };
      continue;
    }
    if (!st.found) {
      last = { state: "not_found" };
      continue;
    }
    if (st.errorCode && st.errorCode !== 0) {
      return { state: "send_error", code: st.errorCode };
    }
    if (st.dateDelivered || st.isDelivered) {
      return {
        state: "delivered",
        deliveredAt: st.dateDelivered || Date.now(),
      };
    }
    last = { state: "accepted" };
  }
  return last;
}

interface ChunkOutcome {
  outcome: "delivered" | "sent-unverified" | "failed";
  detail: string;
  guid?: string;
  deliveredAt?: string;
  retried: boolean;
}

// Send one message with delivery verification and at most ONE retry.
// Retry only when the first attempt is CONFIRMED failed or absent -- never
// on an ambiguous outcome (no double-texting).
async function sendTextVerified(
  chatGuid: string,
  text: string
): Promise<ChunkOutcome> {
  for (let attemptNo = 1; attemptNo <= 2; attemptNo++) {
    const retried = attemptNo === 2;
    const sentAt = Date.now();
    const send = await sendMessage(chatGuid, text);
    let guid = send.guid;

    if (!send.ok) {
      if (send.ambiguous) {
        const lookup = await findSentMessage(chatGuid, text, sentAt);
        if (!lookup.ok) {
          return {
            outcome: "sent-unverified",
            retried,
            detail: `send request failed ambiguously (${send.error}) and status lookup also failed; NOT retried to avoid double-send`,
          };
        }
        if (!lookup.guid) {
          // confirmed absent -- safe to retry
          if (retried) {
            return {
              outcome: "failed",
              retried,
              detail: `send failed twice; message not found on server (${send.error})`,
            };
          }
          log(`Send threw (${send.error}) but message confirmed absent -- retrying once`);
          continue;
        }
        guid = lookup.guid; // it actually went out
      } else {
        // server rejected or unreachable pre-send -- confirmed not sent
        if (retried) {
          return {
            outcome: "failed",
            retried,
            detail: `send rejected twice: ${send.error}`,
          };
        }
        log(`Send rejected (${send.error}) -- retrying once`);
        continue;
      }
    }

    if (!guid) {
      const lookup = await findSentMessage(chatGuid, text, sentAt);
      if (lookup.ok && lookup.guid) guid = lookup.guid;
    }
    if (!guid) {
      return {
        outcome: "sent-unverified",
        retried,
        detail: "server accepted the send but no guid was available to verify delivery",
      };
    }

    const v = await verifyDelivery(guid);
    if (v.state === "delivered") {
      return {
        outcome: "delivered",
        guid,
        deliveredAt: new Date(v.deliveredAt).toISOString(),
        retried,
        detail: "delivery receipt confirmed",
      };
    }
    if (v.state === "accepted") {
      return {
        outcome: "sent-unverified",
        guid,
        retried,
        detail: "accepted by iMessage, no delivery receipt within verification window (recipient may be offline)",
      };
    }
    if (v.state === "unverifiable") {
      return {
        outcome: "sent-unverified",
        guid,
        retried,
        detail: "sent but status checks failed; delivery unknown",
      };
    }
    // send_error or not_found -- confirmed failed
    const why =
      v.state === "send_error"
        ? `iMessage send error code ${v.code}`
        : "message not found on server after send";
    if (retried) {
      return { outcome: "failed", guid, retried, detail: `${why} (after retry)` };
    }
    log(`Send verification failed (${why}) -- retrying once`);
  }
  // unreachable
  return { outcome: "failed", retried: true, detail: "internal error" };
}

// --- Long-Message Chunking -------------------------------------------------------

function chunkText(text: string, maxChars: number): string[] {
  if (text.length <= maxChars) return [text];
  const budget = maxChars - 10; // room for " (99/99)" suffix
  const chunks: string[] = [];
  let rest = text;
  while (rest.length > budget) {
    let cut = budget;
    for (const sep of ["\n\n", "\n", " "]) {
      const idx = rest.lastIndexOf(sep, budget);
      if (idx >= Math.floor(budget * 0.5)) {
        cut = idx;
        break;
      }
    }
    chunks.push(rest.slice(0, cut).trimEnd());
    rest = rest.slice(cut).trimStart();
  }
  if (rest.length > 0) chunks.push(rest);
  const n = chunks.length;
  if (n === 1) return chunks;
  return chunks.map((c, i) => `${c} (${i + 1}/${n})`);
}

// --- Delivery Log ----------------------------------------------------------------

function logDelivery(entry: Record<string, unknown>): void {
  try {
    mkdirSync(dirname(DELIVERY_LOG), { recursive: true });
    appendFileSync(
      DELIVERY_LOG,
      JSON.stringify({ ts: new Date().toISOString(), ...entry }) + "\n"
    );
  } catch (e: any) {
    log(`Warning: could not write delivery log: ${e.message}`);
  }
}

// --- Verified Reply (chunking + verification + logging) ---------------------------

async function replyVerified(
  chatGuid: string,
  text: string,
  tool: string = "bluebubbles_reply"
): Promise<{ ok: boolean; summary: string }> {
  const started = Date.now();
  const chunks = chunkText(text, MAX_MESSAGE_CHARS);
  const results: ChunkOutcome[] = [];
  for (let i = 0; i < chunks.length; i++) {
    if (i > 0) await Bun.sleep(CHUNK_SEND_DELAY_MS);
    const r = await sendTextVerified(chatGuid, chunks[i]!);
    results.push(r);
    if (r.outcome === "failed") break; // don't spray remaining chunks into a dead channel
  }

  const anyFailed = results.some((r) => r.outcome === "failed");
  const outcome = anyFailed
    ? "FAILED"
    : results.every((r) => r.outcome === "delivered")
      ? "delivered"
      : "sent-unverified";

  logDelivery({
    tool,
    chat_guid: chatGuid,
    chars: text.length,
    chunks: chunks.length,
    chunks_attempted: results.length,
    outcome,
    transport: activeBase,
    retried: results.some((r) => r.retried),
    duration_ms: Date.now() - started,
    guids: results.map((r) => r.guid || null),
    detail: results.map((r) => `${r.outcome}: ${r.detail}`).join(" | "),
  });

  const okChunks = results.filter((r) => r.outcome !== "failed").length;
  const parts: string[] = [];
  if (outcome === "FAILED") {
    const failDetail = results.find((r) => r.outcome === "failed")?.detail;
    parts.push(`FAILED: ${failDetail}`);
    if (chunks.length > 1) {
      parts.push(`chunks sent before failure: ${okChunks}/${chunks.length}`);
    }
  } else {
    parts.push(outcome);
    const detail = results.find((r) => r.outcome === "sent-unverified")?.detail;
    if (detail) parts.push(detail);
    const guids = results.map((r) => r.guid).filter(Boolean);
    if (guids.length) parts.push(`guid=${guids.join(",")}`);
    const deliveredAt = results[results.length - 1]?.deliveredAt;
    if (outcome === "delivered" && deliveredAt) parts.push(`delivered_at=${deliveredAt}`);
    if (chunks.length > 1) parts.push(`chunks=${okChunks}/${chunks.length}`);
  }
  parts.push(`transport=${activeBase || "unresolved"}`);
  return { ok: outcome !== "FAILED", summary: parts.join(" | ") };
}

async function sendAttachment(
  chatGuid: string,
  filePath: string,
  message?: string
): Promise<{ ok: boolean; guid?: string; error?: string }> {
  try {
    const file = Bun.file(filePath);
    if (!(await file.exists())) {
      return { ok: false, error: `File not found: ${filePath}` };
    }
    const fileName = filePath.split("/").pop() || "file";
    const formData = new FormData();
    formData.append("chatGuid", chatGuid);
    formData.append("tempGuid", `temp-${crypto.randomUUID()}`);
    formData.append("name", fileName);
    formData.append("method", "private-api");
    if (message) formData.append("message", message);
    formData.append("attachment", file, fileName);

    const base = await resolveTransport();
    const res = await fetch(bbApi(base, "/api/v1/message/attachment"), {
      method: "POST",
      body: formData,
      signal: AbortSignal.timeout(60_000), // uploads can be slow
    });
    const json = (await res.json()) as {
      status: number;
      message: string;
      data?: { guid?: string };
    };
    if (json.status === 200) return { ok: true, guid: json.data?.guid };
    return { ok: false, error: json.message };
  } catch (e: any) {
    if (!(e instanceof TransportUnreachableError)) activeBase = null;
    return { ok: false, error: e.message };
  }
}

async function getMessages(
  chatGuid: string,
  limit: number = 25
): Promise<{ ok: boolean; messages?: any[]; error?: string }> {
  try {
    const res = await bbFetch(
      `/api/v1/chat/${encodeURIComponent(chatGuid)}/message?limit=${limit}&sort=DESC`
    );
    const json = (await res.json()) as { status: number; data: any[] };
    if (json.status === 200) return { ok: true, messages: json.data };
    return { ok: false, error: "Failed to fetch messages" };
  } catch (e: any) {
    return { ok: false, error: e.message };
  }
}

async function searchChats(
  query?: string,
  limit: number = 10
): Promise<{ ok: boolean; chats?: any[]; error?: string }> {
  try {
    const body: any = { limit, with: ["lastMessage"] };
    if (query) body.where = [{ statement: "chat.displayName LIKE :query OR chat.chatIdentifier LIKE :query", args: { query: `%${query}%` } }];
    const res = await bbFetch("/api/v1/chat/query", {
      method: "POST",
      body: JSON.stringify(body),
    });
    const json = (await res.json()) as { status: number; data: any[] };
    if (json.status === 200) return { ok: true, chats: json.data };
    return { ok: false, error: "Failed to search chats" };
  } catch (e: any) {
    return { ok: false, error: e.message };
  }
}

async function downloadAttachment(
  attachmentGuid: string,
  savePath: string
): Promise<{ ok: boolean; path?: string; error?: string }> {
  try {
    const base = await resolveTransport();
    const res = await fetch(
      bbApi(base, `/api/v1/attachment/${encodeURIComponent(attachmentGuid)}/download`)
    );
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}: ${res.statusText}` };
    }
    const buffer = await res.arrayBuffer();
    await Bun.write(savePath, buffer);
    return { ok: true, path: savePath };
  } catch (e: any) {
    return { ok: false, error: e.message };
  }
}

async function markAsRead(chatGuid: string): Promise<void> {
  try {
    await bbFetch(`/api/v1/chat/${encodeURIComponent(chatGuid)}/read`, {
      method: "POST",
    });
  } catch {
    // best effort
  }
}

// --- Webhook Management ------------------------------------------------------

async function cleanStaleWebhooks(): Promise<void> {
  try {
    const res = await bbFetch("/api/v1/webhook");
    const json = (await res.json()) as {
      data: Array<{ id: number; url: string }>;
    };
    const myUrlPrefix = `http://${WEBHOOK_HOST}:${WEBHOOK_PORT}`;
    for (const wh of json.data || []) {
      if (wh.url.startsWith(myUrlPrefix)) {
        await bbFetch(`/api/v1/webhook/${wh.id}`, { method: "DELETE" });
        log(`Cleaned stale webhook #${wh.id}: ${wh.url}`);
      }
    }
  } catch (e: any) {
    log(`Warning: could not clean stale webhooks: ${e.message}`);
  }
}

async function registerWebhook(): Promise<void> {
  const webhookUrl = `http://${WEBHOOK_HOST}:${WEBHOOK_PORT}/webhook?password=${BB_PASSWORD}`;
  try {
    await cleanStaleWebhooks();
    const res = await bbFetch("/api/v1/webhook", {
      method: "POST",
      body: JSON.stringify({
        url: webhookUrl,
        events: ["new-message", "updated-message"],
      }),
    });
    const json = (await res.json()) as { status: number; message: string };
    if (json.status === 200 || json.status === 201) {
      log(`Registered webhook: ${webhookUrl}`);
    } else {
      log(`Warning: webhook registration response: ${json.message}`);
    }
  } catch (e: any) {
    log(`Error registering webhook: ${e.message}`);
  }
}

// --- Logging (stderr so it doesn't pollute MCP stdio) ------------------------

function log(msg: string): void {
  process.stderr.write(`[bluebubbles-channel] ${msg}\n`);
}

// --- MCP Server Setup --------------------------------------------------------

const allowedSet = new Set(ALLOWED_SENDERS);

const mcp = new Server(
  { name: "bluebubbles", version: "1.0.0" },
  {
    capabilities: {
      experimental: {
        "claude/channel": {},
        "claude/channel/permission": {},
      },
      tools: {},
    },
    instructions: [
      'iMessage messages arrive as <channel source="bluebubbles" sender="..." sender_name="..." chat_guid="...">.',
      "Reply with the bluebubbles_reply tool, passing the chat_guid from the tag.",
      "You are Edwin -- reply as yourself. Keep responses concise.",
      "Permission prompts may be relayed -- the sender can reply with yes/no + the request ID.",
    ].join(" "),
  }
);

// --- Reply Tool --------------------------------------------------------------

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "bluebubbles_reply",
      description:
        "Send an iMessage reply via BlueBubbles with delivery verification. " +
        "Long messages are automatically split into (1/2)-style chunks. " +
        "Returns 'delivered' (delivery receipt confirmed), 'sent-unverified' " +
        "(accepted but delivery not yet confirmed -- usually fine), or errors " +
        "with 'FAILED' when the message did NOT go out (treat as not sent).",
      inputSchema: {
        type: "object" as const,
        properties: {
          chat_guid: {
            type: "string",
            description:
              'The chat GUID from the inbound message (e.g. "iMessage;-;+15551234567")',
          },
          text: {
            type: "string",
            description: "The message text to send",
          },
        },
        required: ["chat_guid", "text"],
      },
    },
    {
      name: "bluebubbles_send_attachment",
      description: "Send a file or image via iMessage. The file must exist on the local filesystem.",
      inputSchema: {
        type: "object" as const,
        properties: {
          chat_guid: {
            type: "string",
            description: 'The chat GUID (e.g. "iMessage;-;+15551234567")',
          },
          file_path: {
            type: "string",
            description: "Absolute path to the file to send",
          },
          message: {
            type: "string",
            description: "Optional text message to accompany the attachment",
          },
        },
        required: ["chat_guid", "file_path"],
      },
    },
    {
      name: "bluebubbles_get_messages",
      description: "Get recent messages from an iMessage conversation",
      inputSchema: {
        type: "object" as const,
        properties: {
          chat_guid: {
            type: "string",
            description: 'The chat GUID (e.g. "iMessage;-;+15551234567")',
          },
          limit: {
            type: "number",
            description: "Number of messages to return (default 25, max 100)",
          },
        },
        required: ["chat_guid"],
      },
    },
    {
      name: "bluebubbles_download_attachment",
      description: "Download an attachment (image, file, etc) from an iMessage to the local filesystem so it can be viewed or processed",
      inputSchema: {
        type: "object" as const,
        properties: {
          attachment_guid: {
            type: "string",
            description: "The attachment GUID from the message data (e.g. from get_messages output or webhook payload)",
          },
          save_path: {
            type: "string",
            description: "Absolute path where the file should be saved (e.g. /tmp/received-image.png)",
          },
        },
        required: ["attachment_guid", "save_path"],
      },
    },
    {
      name: "bluebubbles_send_reaction",
      description: "Send a tapback/reaction to a specific iMessage",
      inputSchema: {
        type: "object" as const,
        properties: {
          chat_guid: {
            type: "string",
            description: 'The chat GUID (e.g. "iMessage;-;+15551234567")',
          },
          message_guid: {
            type: "string",
            description: "The GUID of the message to react to",
          },
          reaction: {
            type: "string",
            description: "Reaction type: love, like, dislike, laugh, emphasize, question",
            enum: ["love", "like", "dislike", "laugh", "emphasize", "question"],
          },
        },
        required: ["chat_guid", "message_guid", "reaction"],
      },
    },
    {
      name: "bluebubbles_search_chats",
      description: "Search or list iMessage conversations",
      inputSchema: {
        type: "object" as const,
        properties: {
          query: {
            type: "string",
            description: "Search term to filter chats by name or identifier (optional -- omit to list recent chats)",
          },
          limit: {
            type: "number",
            description: "Number of chats to return (default 10)",
          },
        },
      },
    },
  ],
}));

mcp.setRequestHandler(CallToolRequestSchema, async (req) => {
  const args = req.params.arguments as Record<string, any>;

  if (req.params.name === "bluebubbles_reply") {
    const result = await replyVerified(args.chat_guid, args.text);
    if (result.ok) {
      return { content: [{ type: "text" as const, text: result.summary }] };
    }
    return {
      content: [{ type: "text" as const, text: result.summary }],
      isError: true,
    };
  }

  if (req.params.name === "bluebubbles_send_attachment") {
    const result = await sendAttachment(args.chat_guid, args.file_path, args.message);
    let outcome = "FAILED";
    let summary = `FAILED: ${result.error}`;
    if (result.ok) {
      if (result.guid) {
        const v = await verifyDelivery(result.guid);
        if (v.state === "delivered") {
          outcome = "delivered";
          summary = `delivered | guid=${result.guid} | delivered_at=${new Date(v.deliveredAt).toISOString()}`;
        } else if (v.state === "send_error") {
          outcome = "FAILED";
          summary = `FAILED: attachment accepted but iMessage send error code ${v.code} | guid=${result.guid}`;
        } else if (v.state === "not_found") {
          outcome = "FAILED";
          summary = `FAILED: attachment vanished after send | guid=${result.guid}`;
        } else {
          outcome = "sent-unverified";
          summary = `sent-unverified | accepted, no delivery receipt within verification window | guid=${result.guid}`;
        }
      } else {
        outcome = "sent-unverified";
        summary = "sent-unverified | accepted but no guid returned to verify";
      }
    }
    logDelivery({
      tool: "bluebubbles_send_attachment",
      chat_guid: args.chat_guid,
      file_path: args.file_path,
      chars: (args.message || "").length,
      chunks: 1,
      outcome,
      transport: activeBase,
      guids: [result.guid || null],
      detail: summary,
    });
    if (outcome !== "FAILED") {
      return { content: [{ type: "text" as const, text: `${summary} | transport=${activeBase || "unresolved"}` }] };
    }
    return {
      content: [{ type: "text" as const, text: `${summary} | transport=${activeBase || "unresolved"}` }],
      isError: true,
    };
  }

  if (req.params.name === "bluebubbles_get_messages") {
    const limit = Math.min(args.limit || 25, 100);
    const result = await getMessages(args.chat_guid, limit);
    if (result.ok && result.messages) {
      const formatted = result.messages.map((m: any) => {
        const sender = m.isFromMe ? "You" : (m.handle?.address || "Unknown");
        const time = m.dateCreated ? new Date(m.dateCreated).toLocaleString() : "";
        const text = m.text || (m.attachments?.length ? `[attachment: ${m.attachments[0]?.transferName}]` : "[no text]");
        return `${sender} (${time}): ${text}`;
      }).join("\n");
      return { content: [{ type: "text" as const, text: formatted || "No messages found" }] };
    }
    return {
      content: [{ type: "text" as const, text: `Failed to get messages: ${result.error}` }],
      isError: true,
    };
  }

  if (req.params.name === "bluebubbles_download_attachment") {
    const result = await downloadAttachment(args.attachment_guid, args.save_path);
    if (result.ok) {
      return { content: [{ type: "text" as const, text: `Downloaded to ${result.path}` }] };
    }
    return {
      content: [{ type: "text" as const, text: `Failed to download: ${result.error}` }],
      isError: true,
    };
  }

  if (req.params.name === "bluebubbles_send_reaction") {
    const reactionMap: Record<string, number> = {
      love: 2000, like: 2001, dislike: 2002,
      laugh: 2003, emphasize: 2004, question: 2005,
    };
    const reactionType = reactionMap[args.reaction];
    if (!reactionType) {
      return {
        content: [{ type: "text" as const, text: `Unknown reaction: ${args.reaction}` }],
        isError: true,
      };
    }
    try {
      const res = await bbFetch("/api/v1/message/react", {
        method: "POST",
        body: JSON.stringify({
          chatGuid: args.chat_guid,
          selectedMessageGuid: args.message_guid,
          reaction: reactionType,
        }),
      });
      const json = (await res.json()) as { status: number; message: string };
      const ok = json.status === 200;
      logDelivery({
        tool: "bluebubbles_send_reaction",
        chat_guid: args.chat_guid,
        reaction: args.reaction,
        chars: 0,
        chunks: 1,
        outcome: ok ? "sent-unverified" : "FAILED",
        transport: activeBase,
        detail: ok ? "reaction accepted" : `rejected: ${json.message}`,
      });
      if (ok) {
        return { content: [{ type: "text" as const, text: `Reacted with ${args.reaction}` }] };
      }
      return {
        content: [{ type: "text" as const, text: `FAILED to react: ${json.message}` }],
        isError: true,
      };
    } catch (e: any) {
      logDelivery({
        tool: "bluebubbles_send_reaction",
        chat_guid: args.chat_guid,
        reaction: args.reaction,
        chars: 0,
        chunks: 1,
        outcome: "FAILED",
        transport: activeBase,
        detail: e.message,
      });
      return {
        content: [{ type: "text" as const, text: `FAILED to react: ${e.message}` }],
        isError: true,
      };
    }
  }

  if (req.params.name === "bluebubbles_search_chats") {
    const result = await searchChats(args.query, args.limit || 10);
    if (result.ok && result.chats) {
      const formatted = result.chats.map((c: any) => {
        const name = c.displayName || c.chatIdentifier || "Unknown";
        const lastMsg = c.lastMessage?.text?.substring(0, 80) || "";
        return `${c.guid} | ${name} | ${lastMsg}`;
      }).join("\n");
      return { content: [{ type: "text" as const, text: formatted || "No chats found" }] };
    }
    return {
      content: [{ type: "text" as const, text: `Failed to search chats: ${result.error}` }],
      isError: true,
    };
  }

  throw new Error(`unknown tool: ${req.params.name}`);
});

// --- Permission Relay --------------------------------------------------------

const PermissionRequestSchema = z.object({
  method: z.literal("notifications/claude/channel/permission_request"),
  params: z.object({
    request_id: z.string(),
    tool_name: z.string(),
    description: z.string(),
    input_preview: z.string(),
  }),
});

mcp.setNotificationHandler(PermissionRequestSchema, async ({ params }) => {
  if (!OWNER_PHONE) {
    log("Permission relay skipped -- OWNER_PHONE not configured");
    return;
  }
  const chatGuid = `iMessage;-;${OWNER_PHONE}`;
  const promptMsg =
    `Edwin needs approval to run ${params.tool_name}: ${params.description}\n\n` +
    `Reply "yes ${params.request_id}" or "no ${params.request_id}"`;
  const result = await replyVerified(chatGuid, promptMsg, "permission_relay");
  log(
    `Permission relay for ${params.tool_name} (${params.request_id}): ${result.summary}`
  );
});

// --- Permission verdict regex ------------------------------------------------

const PERMISSION_REPLY_RE = /^\s*(y|yes|n|no)\s+([a-km-z]{5})\s*$/i;

// --- Connect MCP -------------------------------------------------------------

await mcp.connect(new StdioServerTransport());
log("MCP connected");

// --- Webhook HTTP Server -----------------------------------------------------

async function handleWebhook(body: string): Promise<void> {
  let payload: any;
  try {
    payload = JSON.parse(body);
  } catch {
    log("Received non-JSON webhook payload, ignoring");
    return;
  }

  if (payload.type !== "new-message") return;

  const data = payload.data;
  if (!data) return;

  // Filter Edwin's own outbound messages
  if (data.isFromMe) return;

  // Dedup by GUID
  if (isDuplicate(data.guid)) {
    log(`Dedup: skipping ${data.guid}`);
    return;
  }

  // Sender address
  const senderAddress: string = data.handle?.address || "";
  if (!senderAddress) {
    log("No sender address, ignoring");
    return;
  }

  // Allowlist check
  if (!allowedSet.has(senderAddress)) {
    log(`Sender ${senderAddress} not in allowlist, ignoring`);
    return;
  }

  // Group chat filter -- guid contains ;+; for groups
  const chatGuid: string = data.chats?.[0]?.guid || "";
  if (chatGuid.includes(";+;")) {
    log(`Group chat ${chatGuid}, ignoring`);
    return;
  }

  // Message text + attachments
  const text: string = data.text || "";
  const attachments: any[] = data.attachments || [];

  // Build attachment info for the channel tag
  const attachmentMeta: string[] = [];
  for (const att of attachments) {
    const name = att.transferName || "unknown";
    const mime = att.mimeType || "unknown";
    const guid = att.guid || "";
    const size = att.totalBytes ? `${Math.round(att.totalBytes / 1024)} KB` : "";
    attachmentMeta.push(`${name} (${mime}, ${size}, guid: ${guid})`);
  }

  if (!text.trim() && attachmentMeta.length === 0) {
    return;  // truly empty message
  }

  // Mark as read
  await markAsRead(chatGuid);

  // Check for permission verdict before forwarding as chat
  const verdictMatch = PERMISSION_REPLY_RE.exec(text);
  if (verdictMatch) {
    await mcp.notification({
      method: "notifications/claude/channel/permission",
      params: {
        request_id: verdictMatch[2]!.toLowerCase(),
        behavior: verdictMatch[1]!.toLowerCase().startsWith("y")
          ? "allow"
          : "deny",
      },
    });
    log(
      `Permission verdict from ${senderAddress}: ${verdictMatch[1]} ${verdictMatch[2]}`
    );
    return;
  }

  // Resolve sender display name from SENDER_MAP or OWNER_PHONE
  const senderName = senderMap[senderAddress] || senderAddress;

  // Build content: text + attachment descriptions
  const contentParts: string[] = [];
  if (text.trim()) contentParts.push(text);
  if (attachmentMeta.length > 0) {
    contentParts.push(`[Attachments: ${attachmentMeta.join(", ")}]`);
  }

  await mcp.notification({
    method: "notifications/claude/channel",
    params: {
      content: contentParts.join("\n"),
      meta: {
        sender: senderAddress,
        sender_name: senderName,
        chat_guid: chatGuid,
        message_guid: data.guid,
        has_attachments: attachmentMeta.length > 0 ? "true" : "false",
      },
    },
  });

  log(`Forwarded message from ${senderName}: ${text.substring(0, 50)}...`);
}

Bun.serve({
  port: WEBHOOK_PORT,
  hostname: "0.0.0.0",
  async fetch(req) {
    const url = new URL(req.url);

    if (req.method === "GET" && url.pathname === "/health") {
      return new Response(
        JSON.stringify({ status: "ok", channel: "bluebubbles" }),
        { headers: { "Content-Type": "application/json" } }
      );
    }

    if (req.method === "POST" && url.pathname === "/webhook") {
      const body = await req.text();
      handleWebhook(body).catch((e) =>
        log(`Webhook handler error: ${e.message}`)
      );
      return new Response("ok");
    }

    return new Response("not found", { status: 404 });
  },
});

log(`Webhook server listening on 0.0.0.0:${WEBHOOK_PORT}`);

// Register webhook with BlueBubbles
await registerWebhook();

log("BlueBubbles channel ready");
