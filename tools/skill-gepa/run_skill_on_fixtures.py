#!/usr/bin/env python3
"""Fixture-sandboxed skill runner (GEPA task executor).

Executes a CANDIDATE SKILL.md body against a frozen skill-evals fixture day
instead of live data. The candidate never sees the real EDWIN_HOME -- every absolute path
in its text is rewritten to a throwaway sandbox directory that mirrors the
real layout, populated by COPYING the fixture tree (copies, not symlinks, so a
candidate that writes through a path can never touch the frozen fixtures).

Deterministic path mapping applied to the candidate text, in this order
(longest/most-specific first; documented contract -- metric.py and optimize.py
rely on it):

  1. ~/.claude/projects/<project-slug>/memory  ->  <sandbox>/claude-memory
  2. <EDWIN_HOME> (absolute)                    ->  <sandbox>
  3. ~/<EDWIN_HOME basename>                    ->  <sandbox>

  (<project-slug> is EDWIN_HOME with "/" replaced by "-", the format Claude
   Code uses for its per-project session/memory directories.)

Guardrails:
  * headless `claude -p` with cwd=<sandbox>, --setting-sources "" (no user or
    project settings => no hooks, no plugins), --strict-mcp-config with an
    empty server list => NO MCP AT ALL (no bluebubbles, no pm writes; pm_list /
    memory_search absent is fine -- the skill's graceful-degradation rules
    cover missing sources).
  * a `date` shim on PATH freezes the clock to the fixture date, so replays on
    later calendar days still produce the fixture day's brief.
  * wall-clock timeout (default 600s) kills the run; one run at a time
    (flock on <tool>/.runner.lock).

Output: JSON on stdout: {artifact, exit_code, duration_s, cost_usd, num_turns,
sandbox, report_text, error}. Artifact is the newest "Morning Brief -- *.md"
in the sandbox briefing-book (None if the run produced nothing).
"""

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
EDWIN_HOME = Path(os.environ.get("EDWIN_HOME", TOOL_DIR.parent.parent))
PROJECT_SLUG = str(EDWIN_HOME).replace("/", "-")
FIXTURES = EDWIN_HOME / "tools" / "skill-evals" / "fixtures"
CLAUDE_MEMORY = Path.home() / ".claude/projects" / PROJECT_SLUG / "memory"
CREDS_FILE = Path.home() / ".edwin/credentials/anthropic/env"
LOCK_FILE = TOOL_DIR / ".runner.lock"

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
# 40 turns proved too thin for the morning-brief data-gathering phase on
# Haiku (baseline died at max_turns with zero files written, 2026-07-02);
# 100 covers gather + write + self-check with headroom.
DEFAULT_MAX_TURNS = 100
DEFAULT_TIMEOUT = 600


def load_api_key():
    if CREDS_FILE.exists():
        for line in CREDS_FILE.read_text().strip().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1]
    return os.environ.get("ANTHROPIC_API_KEY")


def newest_fixture_date(skill):
    root = FIXTURES / skill
    dates = sorted(d.name for d in root.iterdir() if d.is_dir()) if root.exists() else []
    return dates[-1] if dates else None


def rewrite_candidate(text, sandbox):
    """The deterministic path mapping. Order matters: most specific first."""
    s = str(sandbox)
    home = Path.home()
    slug_mem = f".claude/projects/{PROJECT_SLUG}/memory"
    mapping = [
        (f"~/{slug_mem}", f"{s}/claude-memory"),
        (str(home / slug_mem), f"{s}/claude-memory"),
        (str(EDWIN_HOME), s),
    ]
    try:
        mapping.append((f"~/{EDWIN_HOME.relative_to(home)}", s))
    except ValueError:
        pass
    for old, new in mapping:
        text = text.replace(old, new)
    return text


def materialize(skill, fixture_date, candidate_text, sandbox):
    """Build the sandbox: copy fixture tree, reference files, date shim,
    rewritten SKILL.md, writable output dirs."""
    tree = FIXTURES / skill / fixture_date / "tree"
    if not tree.is_dir():
        raise SystemExit(f"no fixture tree at {tree}")
    sandbox.mkdir(parents=True, exist_ok=True)

    # 1. Fixture tree -> sandbox (COPY; writes through candidate paths can
    #    never touch the frozen fixtures).
    shutil.copytree(tree, sandbox, dirs_exist_ok=True)

    # 2. Static read-only reference data outside EDWIN_HOME (contacts mapping).
    cm = sandbox / "claude-memory"
    cm.mkdir(exist_ok=True)
    contacts = CLAUDE_MEMORY / "reference_contacts.md"
    if contacts.exists():
        shutil.copy2(contacts, cm / "reference_contacts.md")

    # 3. Writable output dirs the skill publishes into.
    (sandbox / "briefing-book" / "docs" / "1. \U0001F4CB Briefs").mkdir(parents=True, exist_ok=True)
    (sandbox / "memory").mkdir(exist_ok=True)

    # 4. date shim: freeze the clock to the fixture date so replays on later
    #    calendar days still write the fixture day's brief. Handles the forms
    #    the skill uses: `date`, `date +FMT`, `date -v-1d +FMT`.
    bindir = sandbox / "bin"
    bindir.mkdir(exist_ok=True)
    shim = bindir / "date"
    shim.write_text(
        "#!/bin/bash\n"
        f"# frozen to fixture day {fixture_date} (skill-gepa sandbox)\n"
        'FLAGS=(); FMT=()\n'
        'for a in "$@"; do case "$a" in +*) FMT+=("$a");; -u|-j) ;; -*) FLAGS+=("$a");; *) ;; esac; done\n'
        f'exec /bin/date -j "${{FLAGS[@]}}" -f "%Y-%m-%d %H:%M:%S" "{fixture_date} 07:30:00" "${{FMT[@]}}"\n'
    )
    shim.chmod(0o755)

    # 5. The candidate, path-rewritten.
    (sandbox / "SKILL.md").write_text(rewrite_candidate(candidate_text, sandbox))

    # 6. Empty MCP config for --strict-mcp-config.
    (sandbox / "mcp-empty.json").write_text('{"mcpServers": {}}')

    # 7. Sandbox CLAUDE.md: the standing guardrails, visible to every turn.
    (sandbox / "CLAUDE.md").write_text(
        "# Sandbox run (skill-gepa)\n\n"
        "You are executing a skill against a FROZEN data snapshot for evaluation.\n\n"
        f"- Write files ONLY inside {sandbox}. Never write outside it.\n"
        "- Do not send messages of any kind (no iMessage, email, Teams, webhooks).\n"
        "- MCP tools (pm_list, pm_add, memory_search, bluebubbles) are unavailable;\n"
        "  treat them as missing data sources and follow the skill's own\n"
        "  graceful-degradation rules. Same for browsers/web intelligence: skip.\n"
        "- If a referenced script or tool does not exist here, note it and move on.\n"
    )


EXEC_PROMPT = (
    "Read {sandbox}/SKILL.md and execute it fully, right now, as the skill agent. "
    "This is a sandboxed evaluation run against a frozen data snapshot dated {date}. "
    "Hard rules: write only inside {sandbox}; no messages or MCP sends of any kind; "
    "MCP tools and browsers are unavailable -- treat those steps as missing data "
    "sources per the skill's own rules; if a referenced script/tool is absent, note "
    "it and continue. Produce the artifact and finish with the Completion Report."
)


def run(args):
    skill = args.skill
    fixture_date = args.fixture_date or newest_fixture_date(skill)
    if not fixture_date:
        raise SystemExit(f"no fixtures for {skill}")

    candidate_file = Path(args.candidate) if args.candidate else EDWIN_HOME / "skills" / skill / "SKILL.md"
    candidate_text = candidate_file.read_text()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    sandbox = (Path(args.sandbox_dir) if args.sandbox_dir else TOOL_DIR / "runs" / f"{skill}-{stamp}").resolve()
    materialize(skill, fixture_date, candidate_text, sandbox)

    anthropic_ak = load_api_key()
    if not anthropic_ak:
        raise SystemExit("no ANTHROPIC_API_KEY (checked ~/.edwin/credentials/anthropic/env and env)")

    env = dict(os.environ)
    env["ANTHROPIC_API_KEY"] = anthropic_ak
    env["PATH"] = f"{sandbox}/bin:{env.get('PATH', '')}"
    env.pop("CLAUDECODE", None)  # not a nested-session signal

    claude_bin = shutil.which("claude")
    cmd = [
        claude_bin, "-p", EXEC_PROMPT.format(sandbox=sandbox, date=fixture_date),
        "--model", args.model,
        "--max-turns", str(args.max_turns),
        "--dangerously-skip-permissions",
        "--setting-sources", "",
        "--strict-mcp-config", "--mcp-config", str(sandbox / "mcp-empty.json"),
        "--output-format", "json",
    ]

    result = {"skill": skill, "fixture_date": fixture_date, "sandbox": str(sandbox),
              "candidate": str(candidate_file), "model": args.model,
              "artifact": None, "exit_code": None, "duration_s": None,
              "cost_usd": None, "num_turns": None, "report_text": None, "error": None}

    # One run at a time.
    lock = open(LOCK_FILE, "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(sandbox), env=env,
                              capture_output=True, text=True, timeout=args.timeout)
        result["exit_code"] = proc.returncode
        out = proc.stdout.strip()
        try:
            payload = json.loads(out)
            result["cost_usd"] = payload.get("total_cost_usd")
            result["num_turns"] = payload.get("num_turns")
            result["report_text"] = payload.get("result")
        except (json.JSONDecodeError, AttributeError):
            result["report_text"] = out[-4000:]
        if proc.returncode != 0:
            result["error"] = (proc.stderr or out)[-2000:] or f"exit {proc.returncode}"
    except subprocess.TimeoutExpired:
        result["error"] = f"timeout after {args.timeout}s"
        result["exit_code"] = -1
    finally:
        result["duration_s"] = round(time.time() - t0, 1)
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()

    briefs = sorted((sandbox / "briefing-book" / "docs" / "1. \U0001F4CB Briefs").glob("Morning Brief -- *.md"),
                    key=lambda p: p.stat().st_mtime)
    if briefs:
        result["artifact"] = str(briefs[-1])

    (sandbox / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0 if result["artifact"] and not result["error"] else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skill", default="morning-brief")
    ap.add_argument("--fixture-date", default=None, help="default: newest frozen day")
    ap.add_argument("--candidate", default=None, help="path to candidate SKILL.md (default: the real one)")
    ap.add_argument("--sandbox-dir", default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-turns", type=int, default=DEFAULT_MAX_TURNS)
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = ap.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
