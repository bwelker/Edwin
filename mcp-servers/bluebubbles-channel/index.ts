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
 *   WEBHOOK_PORT      - Port for the webhook listener (default: 18800)
 *   WEBHOOK_HOST      - LAN IP visible to the BlueBubbles server (default: auto-detect)
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

// --- Configuration -----------------------------------------------------------

const BB_URL = process.env.BB_URL;
const BB_PASSWORD = process.env.BB_PASSWORD;
if (!BB_URL || !BB_PASSWORD) {
  process.stderr.write(
    "[bluebubbles-channel] ERROR: BB_URL and BB_PASSWORD environment variables are required.\n"
  );
  process.exit(1);
}

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

const BB_API = (path: string) =>
  `${BB_URL}${path}${path.includes("?") ? "&" : "?"}password=${BB_PASSWORD}`;

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
  return fetch(BB_API(path), {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
}

async function sendMessage(
  chatGuid: string,
  text: string
): Promise<{ ok: boolean; error?: string }> {
  try {
    const res = await bbFetch("/api/v1/message/text", {
      method: "POST",
      body: JSON.stringify({
        chatGuid,
        message: text,
        method: "private-api",
      }),
    });
    const json = (await res.json()) as { status: number; message: string };
    if (json.status === 200) return { ok: true };
    return { ok: false, error: json.message };
  } catch (e: any) {
    return { ok: false, error: e.message };
  }
}

async function sendAttachment(
  chatGuid: string,
  filePath: string,
  message?: string
): Promise<{ ok: boolean; error?: string }> {
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

    const res = await fetch(BB_API("/api/v1/message/attachment"), {
      method: "POST",
      body: formData,
    });
    const json = (await res.json()) as { status: number; message: string };
    if (json.status === 200) return { ok: true };
    return { ok: false, error: json.message };
  } catch (e: any) {
    return { ok: false, error: e.message };
  }
}

async function getMessages(
  chatGuid: string,
  limit: number = 25
): Promise<{ ok: boolean; messages?: any[]; error?: string }> {
  try {
    const res = await bbFetch(
      `/api/v1/chat/${encodeURIComponent(chatGuid)}/message?limit=${limit}&sort=desc`
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
    const res = await fetch(
      BB_API(`/api/v1/attachment/${encodeURIComponent(attachmentGuid)}/download`)
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
      description: "Send an iMessage reply via BlueBubbles",
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
    const result = await sendMessage(args.chat_guid, args.text);
    if (result.ok) {
      return { content: [{ type: "text" as const, text: "sent" }] };
    }
    return {
      content: [{ type: "text" as const, text: `Failed to send: ${result.error}` }],
      isError: true,
    };
  }

  if (req.params.name === "bluebubbles_send_attachment") {
    const result = await sendAttachment(args.chat_guid, args.file_path, args.message);
    if (result.ok) {
      return { content: [{ type: "text" as const, text: "attachment sent" }] };
    }
    return {
      content: [{ type: "text" as const, text: `Failed to send attachment: ${result.error}` }],
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
      if (json.status === 200) {
        return { content: [{ type: "text" as const, text: `Reacted with ${args.reaction}` }] };
      }
      return {
        content: [{ type: "text" as const, text: `Failed to react: ${json.message}` }],
        isError: true,
      };
    } catch (e: any) {
      return {
        content: [{ type: "text" as const, text: `Failed to react: ${e.message}` }],
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
  await sendMessage(chatGuid, promptMsg);
  log(`Permission relay sent for ${params.tool_name} (${params.request_id})`);
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
        request_id: verdictMatch[2].toLowerCase(),
        behavior: verdictMatch[1].toLowerCase().startsWith("y")
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
