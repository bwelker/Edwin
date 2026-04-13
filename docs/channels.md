# Channels

Edwin isn't useful if you have to open your laptop to talk to it. Channels are how Edwin reaches you -- and how it stays aware of its own work.

Channels serve two purposes:

**1. Edwin talks to you.** Your morning brief arrives as a Telegram message before you're out of bed. A commitment you made in a meeting gets flagged while you're driving. An overnight research task finishes and the summary hits your phone at 6 AM. Edwin is proactive -- it doesn't wait for you to ask. Channels are what make that possible.

**2. Edwin talks to itself.** When a scheduled connector finishes syncing, or a skill completes its work, or something needs attention -- that event flows through an internal channel back to the orchestrator. Without this, the main Edwin session would be blind to everything happening in the background. The events channel is Edwin's nervous system.

## Telegram Setup

Edwin ships with Telegram as the default communication channel. Telegram's BotFather makes it simple: create a bot, get a token, give it to Edwin during setup. You get a private 1:1 chat with your AI chief of staff on your phone, your tablet, your desktop -- wherever Telegram runs.

**Steps:**

1. **Create your bot.** Open Telegram, search `@BotFather`, send `/newbot`, follow the prompts. Copy the bot token.
2. **Run `./setup.sh`.** The Telegram section (step 6) will prompt for your token, validate it, and create the channel config at `~/.claude/channels/telegram/`.
3. **Install the plugin** (first time only). In Claude Code, run:
   ```
   /install-plugin telegram@claude-plugins-official
   ```
   The repo includes `.claude/settings.json` which enables the plugin automatically, but the plugin binary must be installed once per machine.
4. **Launch Edwin with the channel:**
   ```bash
   claude --dangerously-load-development-channels plugin:telegram@claude-plugins-official server:events
   ```
   The `--dangerously-load-development-channels` flag is required because the events channel is a custom MCP server, not an official plugin. Without it, event notifications silently fail to reach the session.
5. **Pair your phone.** Open Telegram and DM your bot. It will reply with a pairing code.
6. **Approve the pairing.** In the Claude Code terminal:
   ```
   /telegram:access pair <CODE>
   ```
7. **Lock down access** (recommended). Once paired:
   ```
   /telegram:access policy allowlist
   ```
   This restricts the bot to only your approved Telegram account.

> **Note:** Anthropic Team/Enterprise accounts require the org admin to enable channel notifications in the organization settings. Pro accounts have this enabled by default.

## Advanced: iMessage

For macOS users who want Edwin to communicate via iMessage instead of Telegram, a BlueBubbles-based iMessage channel is available as an advanced configuration. This requires a dedicated macOS instance (physical or VM) running the BlueBubbles server. Setup guide coming in a future release.

## Building Your Own Channel

The channel interface is simple: receive messages, send messages, route events. If you use Slack, WhatsApp, Signal, or something else as your primary messaging platform -- build a channel connector and contribute it back. The events-channel MCP server in the repo shows the pattern.
