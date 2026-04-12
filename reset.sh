#!/bin/bash
# Edwin Reset Script
# Selective teardown -- choose what to reset.

set -e

EDWIN_HOME="$(cd "$(dirname "$0")" && pwd)"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo -e "${YELLOW}Edwin Reset${NC}"
echo "Select what to reset. Each step is optional."
echo ""

# 1. Containers
read -p "Stop and remove Edwin Docker containers? [y/N]: " choice
if [[ "$choice" =~ ^[Yy]$ ]]; then
    cd "$EDWIN_HOME"
    docker compose down -v 2>/dev/null && echo -e "${GREEN}  ✓ Containers stopped and removed.${NC}" || echo "  No containers running."
else
    echo "  Containers unchanged."
fi
echo ""

# 2. .env
read -p "Delete .env file? [y/N]: " choice
if [[ "$choice" =~ ^[Yy]$ ]]; then
    rm -f "$EDWIN_HOME/.env"
    echo -e "${GREEN}  ✓ .env deleted.${NC}"
else
    echo "  .env preserved."
fi
echo ""

# 3. Data
read -p "Wipe data/ directory? (ALL synced data -- emails, notes, calendar, etc.) [y/N]: " choice
if [[ "$choice" =~ ^[Yy]$ ]]; then
    rm -rf "$EDWIN_HOME/data/"
    mkdir -p "$EDWIN_HOME/data"
    echo -e "${GREEN}  ✓ data/ wiped.${NC}"
else
    echo "  data/ preserved."
fi
echo ""

# 4. Memory
read -p "Wipe memory/ directory? (session summaries, conversation state, memory index) [y/N]: " choice
if [[ "$choice" =~ ^[Yy]$ ]]; then
    rm -rf "$EDWIN_HOME/memory/"
    mkdir -p "$EDWIN_HOME/memory/sessions"
    echo -e "${GREEN}  ✓ memory/ wiped.${NC}"
else
    echo "  memory/ preserved."
fi
echo ""

# 5. Briefing book content
read -p "Wipe briefing book content? (keeps folder structure, removes files) [y/N]: " choice
if [[ "$choice" =~ ^[Yy]$ ]]; then
    find "$EDWIN_HOME/briefing-book/docs" -type f -name "*.md" -delete 2>/dev/null
    echo -e "${GREEN}  ✓ Briefing book content wiped (structure preserved).${NC}"
else
    echo "  Briefing book preserved."
fi
echo ""

# 6. CLAUDE.md
read -p "Delete CLAUDE.md? (removes personalization -- wizard will regenerate on next run) [y/N]: " choice
if [[ "$choice" =~ ^[Yy]$ ]]; then
    rm -f "$EDWIN_HOME/CLAUDE.md"
    echo -e "${GREEN}  ✓ CLAUDE.md deleted. Wizard will regenerate on next 'claude' session.${NC}"
else
    echo "  CLAUDE.md preserved."
fi
echo ""

# Summary
echo -e "${GREEN}Reset complete.${NC}"
echo ""
echo "  Next steps:"
echo "    ./setup.sh     ← rebuild containers and infrastructure"
echo "    claude          ← re-run the setup wizard (if CLAUDE.md was deleted)"
echo ""
