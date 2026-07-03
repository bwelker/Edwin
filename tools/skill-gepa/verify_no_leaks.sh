#!/bin/bash
# Post-run leak check: candidate sandbox runs must not touch the real
# workspace. Verifies (1) the real morning brief is byte-identical to the
# pre-run checksum, (2) no real briefing-book/memory/skills files were
# modified since a reference timestamp file.
# Usage: verify_no_leaks.sh <reference-file> [expected-md5]
set -euo pipefail
REF="${1:?usage: verify_no_leaks.sh <reference-file> [expected-md5]}"
EXPECTED="${2:-}"
E2="${EDWIN_HOME:-$HOME/Edwin}"
BRIEF="${BRIEF_FILE:-$E2/briefing-book/docs/1. 📋 Briefs/Morning Brief -- latest.md}"

fail=0
if [[ -n "$EXPECTED" ]]; then
  actual=$(md5 -q "$BRIEF")
  if [[ "$actual" != "$EXPECTED" ]]; then
    echo "LEAK: real morning brief changed ($actual != $EXPECTED)"; fail=1
  else
    echo "ok: real morning brief untouched ($actual)"
  fi
fi

leaks=$(find "$E2/briefing-book" "$E2/memory" "$E2/skills" "$E2/data" \
  -newer "$REF" -type f \
  ! -path "*/.git/*" ! -name ".session-watcher-state.json" \
  ! -path "*/memory/captured/*" ! -path "*/data/skill-evals/*" 2>/dev/null || true)
if [[ -n "$leaks" ]]; then
  echo "files modified since $(basename "$REF") (review each -- other Edwin processes also write here):"
  echo "$leaks"
else
  echo "ok: no real workspace files modified since reference"
fi
exit $fail
