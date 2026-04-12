#!/bin/bash
# Edwin Setup Script
# Installs infrastructure, pulls models, configures the environment.
# Run once after cloning: ./setup.sh

set -e

EDWIN_HOME="$(cd "$(dirname "$0")" && pwd)"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo ""
echo "  ╔═══════════════════════════════════╗"
echo "  ║         Edwin Setup               ║"
echo "  ║   Personal AI Chief of Staff      ║"
echo "  ╚═══════════════════════════════════╝"
echo ""

# ── Cleanup trap ─────────────────────────────────────────────────────────────
cleanup() {
    if [ $? -ne 0 ]; then
        echo -e "\n${RED}Setup failed. Cleaning up...${NC}"
        cd "$EDWIN_HOME" && docker compose down 2>/dev/null
        echo -e "${RED}Containers stopped. Fix the issue above and re-run ./setup.sh${NC}"
    fi
}
trap cleanup EXIT

# ── Port finder ──────────────────────────────────────────────────────────────
find_free_port() {
    local start_port=$1
    local port=$start_port
    local max_tries=10
    local i=0
    while [ $i -lt $max_tries ]; do
        if ! lsof -i :$port &>/dev/null; then
            echo $port
            return 0
        fi
        port=$((port + 2))
        i=$((i + 1))
    done
    echo -e "${RED}Could not find a free port starting from $start_port${NC}" >&2
    return 1
}

# ── 1. Check Docker ──────────────────────────────────────────────────────────

echo -e "${YELLOW}[1/6]${NC} Checking Docker..."

if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker not found.${NC}"
    echo "  Install Docker Desktop: https://docker.com/products/docker-desktop"
    echo "  Then re-run this script."
    exit 1
fi

if ! docker info &> /dev/null; then
    echo -e "${RED}Docker is installed but not running.${NC}"
    echo "  Start Docker Desktop and re-run this script."
    exit 1
fi

echo -e "${GREEN}  Docker is running.${NC}"

# ── 2. Start Qdrant + Neo4j ──────────────────────────────────────────────────

echo -e "${YELLOW}[2/6]${NC} Starting Qdrant + Neo4j..."

cd "$EDWIN_HOME"

if docker ps --format '{{.Names}}' | grep -q 'edwin-qdrant'; then
    QDRANT_PORT=$(docker port edwin-qdrant 6333/tcp 2>/dev/null | cut -d: -f2)
    echo -e "${GREEN}  edwin-qdrant already running on port ${QDRANT_PORT}.${NC}"
else
    QDRANT_PORT=$(find_free_port 6380)
    QDRANT_GRPC=$((QDRANT_PORT + 1))
    echo "  Found free port: $QDRANT_PORT"
    QDRANT_PORT=$QDRANT_PORT QDRANT_GRPC=$QDRANT_GRPC docker compose up -d edwin-qdrant
    echo -e "${GREEN}  edwin-qdrant started on port ${QDRANT_PORT}.${NC}"
fi

if docker ps --format '{{.Names}}' | grep -q 'edwin-neo4j'; then
    NEO4J_BOLT=$(docker port edwin-neo4j 7687/tcp 2>/dev/null | cut -d: -f2)
    NEO4J_WEB=$(docker port edwin-neo4j 7474/tcp 2>/dev/null | cut -d: -f2)
    echo -e "${GREEN}  edwin-neo4j already running on port ${NEO4J_BOLT} (web UI: ${NEO4J_WEB}).${NC}"
else
    NEO4J_WEB=$(find_free_port 7476)
    NEO4J_BOLT=$(find_free_port 7690)
    echo "  Found free ports: bolt=${NEO4J_BOLT}, web=${NEO4J_WEB}"
    NEO4J_WEB=$NEO4J_WEB NEO4J_BOLT=$NEO4J_BOLT docker compose up -d edwin-neo4j
    echo -e "${GREEN}  edwin-neo4j started on port ${NEO4J_BOLT} (web UI: ${NEO4J_WEB}).${NC}"
fi

# ── 3. Check Ollama + pull embedding model ───────────────────────────────────

echo -e "${YELLOW}[3/6]${NC} Checking Ollama..."

if ! command -v ollama &> /dev/null; then
    echo -e "${RED}Ollama not found.${NC}"
    echo "  Install Ollama: https://ollama.com"
    echo "  Then re-run this script."
    exit 1
fi

echo -e "${GREEN}  Ollama is installed.${NC}"

# Detect RAM and recommend model
RAM_GB=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f", $1/1073741824}')

if [ -z "$RAM_GB" ]; then
    RAM_GB=16  # default assumption
fi

echo "  Detected ${RAM_GB}GB RAM."

if [ "$RAM_GB" -ge 16 ]; then
    DEFAULT_MODEL="qwen3-embedding:8b"
    echo "  Recommended embedding model: qwen3-embedding:8b (best quality, ~4.7GB)"
else
    DEFAULT_MODEL="nomic-embed-text"
    echo "  Recommended embedding model: nomic-embed-text (lightweight, ~274MB)"
    echo "  (qwen3-embedding:8b recommended for 16GB+ systems)"
fi

read -p "  Use ${DEFAULT_MODEL}? [Y/n/other model name]: " model_choice
model_choice="${model_choice:-Y}"

if [[ "$model_choice" =~ ^[Yy]$ ]]; then
    EMBED_MODEL="$DEFAULT_MODEL"
elif [[ "$model_choice" =~ ^[Nn]$ ]]; then
    if [ "$DEFAULT_MODEL" = "qwen3-embedding:8b" ]; then
        EMBED_MODEL="nomic-embed-text"
    else
        EMBED_MODEL="qwen3-embedding:8b"
    fi
else
    EMBED_MODEL="$model_choice"
fi

echo "  Pulling ${EMBED_MODEL}..."
ollama pull "$EMBED_MODEL"
echo -e "${GREEN}  Embedding model ready: ${EMBED_MODEL}${NC}"

# ── 4. Python dependencies ───────────────────────────────────────────────────

echo -e "${YELLOW}[4/6]${NC} Installing Python dependencies..."

# Create a venv for Edwin's Python dependencies
VENV_DIR="$EDWIN_HOME/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "  Creating Python virtual environment..."
    python3 -m venv "$VENV_DIR"
fi
VENV_PIP="$VENV_DIR/bin/pip"

if [ -f "$EDWIN_HOME/requirements.txt" ]; then
    "$VENV_PIP" install -q -r "$EDWIN_HOME/requirements.txt" 2>/dev/null || \
    echo -e "${YELLOW}  Warning: pip install failed. You may need to install dependencies manually.${NC}"
    echo -e "${GREEN}  Python dependencies installed.${NC}"
else
    echo -e "${YELLOW}  No requirements.txt found -- skipping.${NC}"
fi

# MCP server dependencies (neo4j, pm both need the mcp package)
for req_file in "$EDWIN_HOME"/mcp-servers/*/requirements.txt; do
    [ -f "$req_file" ] || continue
    echo "  Installing deps from ${req_file#$EDWIN_HOME/}..."
    "$VENV_PIP" install -q -r "$req_file" 2>/dev/null || \
    echo -e "${YELLOW}  Warning: pip install failed for $req_file${NC}"
done
echo -e "${GREEN}  MCP server dependencies installed.${NC}"

# ── 5. Write .env defaults ───────────────────────────────────────────────────

echo -e "${YELLOW}[5/6]${NC} Configuring environment..."

if [ ! -f "$EDWIN_HOME/.env" ]; then
    cat > "$EDWIN_HOME/.env" << ENVEOF
# Edwin Configuration
# Generated by setup.sh -- edit as needed

# Embedding model (set during setup)
EDWIN_EMBED_MODEL=${EMBED_MODEL}

# Timezone (auto-detected, override if needed)
EDWIN_TZ=$(python3 -c "import time; print(time.tzname[0])" 2>/dev/null || echo "UTC")

# Infrastructure ports (auto-detected by setup.sh)
EDWIN_QDRANT_PORT=${QDRANT_PORT}
EDWIN_NEO4J_PORT=${NEO4J_BOLT}

# Neo4j credentials (match docker-compose.yml)
EDWIN_NEO4J_USER=neo4j
EDWIN_NEO4J_PASS=changeme

# Ollama endpoint
EDWIN_OLLAMA_URL=http://localhost:11434

# Events channel URL (used by Plombery to post job/skill events)
EVENTS_URL=http://127.0.0.1:8790/job-complete
SKILL_EVENTS_URL=http://127.0.0.1:8790/run-skill

# ── User Config (filled by setup wizard) ──
# EDWIN_EMAIL=
# AZURE_TENANT_ID=
# AZURE_CLIENT_ID=
# AZURE_CLIENT_SECRET=
ENVEOF
    echo -e "${GREEN}  .env created with defaults.${NC}"
else
    echo -e "${GREEN}  .env already exists -- not overwriting.${NC}"
fi

# Ensure PM data directory exists
mkdir -p "${EDWIN_HOME}/data/pm"

# Use venv python for MCP servers
PYTHON3_PATH="$VENV_DIR/bin/python3"

# Generate .mcp.json for Claude Code MCP server discovery
if [ ! -f "$EDWIN_HOME/.mcp.json" ]; then
    cat > "$EDWIN_HOME/.mcp.json" << MCPEOF
{
  "mcpServers": {
    "edwin-qdrant": {
      "command": "node",
      "args": ["${EDWIN_HOME}/mcp-servers/qdrant/index.js"],
      "env": {
        "QDRANT_URL": "http://localhost:${QDRANT_PORT}",
        "OLLAMA_URL": "http://localhost:11434",
        "EMBEDDING_MODEL": "${EMBED_MODEL}",
        "COLLECTION": "edwin-memory",
        "WORKSPACE_PATH": "${EDWIN_HOME}"
      }
    },
    "edwin-neo4j": {
      "command": "${PYTHON3_PATH}",
      "args": ["${EDWIN_HOME}/mcp-servers/neo4j/server.py"],
      "env": {
        "NEO4J_URI": "bolt://localhost:${NEO4J_BOLT}",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "changeme"
      }
    },
    "edwin-pm": {
      "command": "${PYTHON3_PATH}",
      "args": ["${EDWIN_HOME}/mcp-servers/pm/server.py"],
      "env": {
        "PM_DB_PATH": "${EDWIN_HOME}/data/pm/prospective.db"
      }
    },
    "events": {
      "command": "bun",
      "args": ["${EDWIN_HOME}/mcp-servers/events-channel/index.ts"],
      "env": {
        "EVENTS_PORT": "8790"
      }
    }
  }
}
MCPEOF
    echo -e "${GREEN}  .mcp.json created with MCP server config.${NC}"
else
    echo -e "${GREEN}  .mcp.json already exists -- not overwriting.${NC}"
fi

# ── 6. Telegram channel (optional) ──────────────────────────────────────────

echo -e "${YELLOW}[6/6]${NC} Telegram mobile access..."

TELEGRAM_BOT_USERNAME=""

read -p "  Want to connect Telegram for mobile access? [Y/n]: " tg_choice
tg_choice="${tg_choice:-Y}"

if [[ "$tg_choice" =~ ^[Yy]$ ]]; then

    CHANNEL_DIR="$HOME/.claude/channels/telegram"
    ENV_FILE="$CHANNEL_DIR/.env"
    ACCESS_FILE="$CHANNEL_DIR/access.json"
    APPROVED_DIR="$CHANNEL_DIR/approved"

    # JSON helper -- use jq if available, fall back to grep/sed
    has_jq=false
    command -v jq &>/dev/null && has_jq=true

    echo ""
    echo "  Open Telegram, search @BotFather, send /newbot, follow the prompts, copy the token."
    echo ""

    while true; do
        read -p "  Paste your bot token: " tg_token
        tg_token=$(echo "$tg_token" | xargs)  # trim whitespace

        if [[ -z "$tg_token" ]]; then
            echo -e "  ${RED}No token entered.${NC}"
            continue
        fi

        # Validate via getMe
        printf "  Validating..."
        tg_response=$(curl -s "https://api.telegram.org/bot${tg_token}/getMe" 2>/dev/null || true)

        if $has_jq; then
            tg_ok=$(echo "$tg_response" | jq -r '.ok // empty')
        else
            tg_ok=$(echo "$tg_response" | grep -o '"ok"[[:space:]]*:[[:space:]]*true' | head -1)
        fi

        if [[ "$tg_ok" != "true" ]] && [[ -z "$tg_ok" || "$tg_ok" == "false" ]]; then
            echo -e " ${RED}Invalid token. Try again.${NC}"
            continue
        fi

        # Extract bot username
        if $has_jq; then
            TELEGRAM_BOT_USERNAME=$(echo "$tg_response" | jq -r '.result.username // empty')
        else
            TELEGRAM_BOT_USERNAME=$(echo "$tg_response" | grep -o '"username":"[^"]*"' | head -1 | sed 's/"username":"//;s/"$//')
        fi

        echo -e " ${GREEN}Valid!${NC} Bot: @${TELEGRAM_BOT_USERNAME}"
        break
    done

    # Save config
    mkdir -p "$CHANNEL_DIR" "$APPROVED_DIR"

    printf "TELEGRAM_BOT_TOKEN=%s\n" "$tg_token" > "$ENV_FILE"
    chmod 600 "$ENV_FILE"

    cat > "$ACCESS_FILE" <<'ACCESSEOF'
{
  "dmPolicy": "pairing",
  "allowFrom": [],
  "groups": {},
  "pending": {}
}
ACCESSEOF
    chmod 600 "$ACCESS_FILE"

    echo -e "  ${GREEN}Token saved.${NC}"
    echo ""
    echo "  To connect your phone:"
    echo "    1. Install the plugin (first time only):"
    echo "         claude /install-plugin telegram@claude-plugins-official"
    echo "    2. Launch Edwin:  claude --dangerously-load-development-channels plugin:telegram@claude-plugins-official server:events"
    echo "    3. Open Telegram and message @${TELEGRAM_BOT_USERNAME}"
    echo "    4. You'll get a pairing code -- enter it in the terminal:"
    echo "         /telegram:access pair <CODE>"
    echo "    5. Lock down access:  /telegram:access policy allowlist"

else
    echo -e "${GREEN}  Skipped.${NC}"
fi

# ── Done ─────────────────────────────────────────────────────────────────────

echo ""
echo -e "${GREEN}  ✓ Setup complete.${NC}"
echo ""
echo "  Infrastructure:"
echo "    Qdrant:  http://localhost:${QDRANT_PORT}"
echo "    Neo4j:   http://localhost:${NEO4J_WEB} (bolt: ${NEO4J_BOLT})"
echo "    Ollama:  http://localhost:11434 (model: ${EMBED_MODEL})"
if [[ -n "$TELEGRAM_BOT_USERNAME" ]]; then
echo "    Telegram: @${TELEGRAM_BOT_USERNAME}"
fi
echo ""
echo "  Next step:"
echo "    cd $EDWIN_HOME"
if [[ -n "$TELEGRAM_BOT_USERNAME" ]]; then
echo "    claude /install-plugin telegram@claude-plugins-official   # first time only"
echo "    claude --dangerously-load-development-channels plugin:telegram@claude-plugins-official server:events"
echo ""
echo "  Note: --dangerously-load-development-channels is required for the events channel"
echo "  (a custom MCP server, not an official plugin). Without it, event notifications"
echo "  silently fail to reach the session."
else
echo "    claude"
fi
echo ""
echo "  Edwin will guide you through the rest."
echo ""
