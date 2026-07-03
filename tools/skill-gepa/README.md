# skill-gepa

GEPA (reflective prompt evolution, arXiv 2507.19457 / gepa-ai/gepa) applied to
Edwin's SKILL.md files. The optimization target is the skill body itself; the
metric is the skill-evals deterministic check suite run against the artifact a
candidate produces from a FROZEN fixture day. No live data, no live sends, no
mutation of the real skill.

## The loop

```
candidate SKILL.md text
  -> run_skill_on_fixtures.py   (headless `claude -p`, Haiku, fixture sandbox)
  -> sandbox artifact
  -> metric.py                  (skill-evals suite: score = pass fraction,
                                 side info = failing checks' names + messages)
  -> GEPA reflection            (claude-sonnet-5 reads the side info,
                                 proposes a mutated skill body)
  -> repeat under --max-metric-calls / --max-cost-usd
```

## Files

- `run_skill_on_fixtures.py` -- fixture-sandboxed runner. Materializes a
  throwaway dir mirroring the real layout (fixture tree COPIED in, never
  symlinked, so candidate writes can't touch the frozen inputs), rewrites the
  candidate's absolute paths via a deterministic string mapping (documented in
  the module docstring), freezes `date` with a PATH shim, and executes with
  `--setting-sources ""` (no hooks/plugins) + `--strict-mcp-config` and an
  empty MCP list (no bluebubbles, no pm writes -- the skill's own
  graceful-degradation rules cover the missing sources). 10-min wall clock
  timeout, flock so only one run at a time.
- `metric.py` -- scores a runner result with the skill's skill-evals suite.
  Never writes `.eval-history.jsonl` (optimization traffic must not pollute
  the daily regression baseline). Hard fails (no artifact, timeout) score 0.
- `optimize.py` -- the GEPA adapter + runner. Run with `venv/bin/python`.
  Budget knobs: `--max-metric-calls` (default 25) and `--max-cost-usd`
  (default 15, summed from the runner's reported cost; trips a stop callback).
- `candidates/<stamp>-<skill>-{best.md,diff.patch,scores.json}` -- output.
  **The live `skills/<skill>/SKILL.md` is never modified.** Adopting a
  candidate is the operator/orchestrator's call: review the diff, then copy best.md
  over the skill and let the next real run + `sys-skill-evals` confirm.
- `runs/` -- per-call sandboxes + logs. Safe to `trash` after review.

## Usage

```bash
# one sandboxed run of the CURRENT skill (baseline / smoke test)
python3 run_skill_on_fixtures.py --skill morning-brief
python3 metric.py --result runs/<sandbox>/result.json

# bounded optimization
venv/bin/python optimize.py --skill morning-brief --max-metric-calls 25 --max-cost-usd 15
```

Setup (already done once): `python3.12 -m venv venv && venv/bin/pip install gepa`.
Provide the Anthropic API key via `~/.edwin/credentials/anthropic/env`. Task model Haiku
(claude-haiku-4-5-20251001), reflection model claude-sonnet-5.

## Trainset growth + the production run (nightwatch)

One frozen day is proof-of-life thin -- GEPA's pareto selection needs variety
to avoid overfitting the skill text to a single day's data (with 1 day,
train == val and every "improvement" is in-sample). The path to a real run:

1. **Weekly fixture freeze** (nightwatch task, any night):
   `tools/skill-evals/skill-evals fixtures freeze morning-brief` -- each freeze
   adds a dated day under `tools/skill-evals/fixtures/morning-brief/`.
   `optimize.py` picks up every frozen day automatically.
2. **Once >=3 days exist**: a full run is a valid nightwatch task --
   `venv/bin/python optimize.py --skill morning-brief --max-metric-calls 150
   --max-cost-usd 40`. Expect hours of wall clock (each metric call is a full
   Haiku skill execution, ~2-6 min); it is the night's heavy solo task.
3. Richer metric = better optimization: the side info is only as sharp as the
   suite. When self-retro corrections add checks to
   `tools/skill-evals/suites/morning-brief.json`, GEPA inherits them for free.

Any skill with a full suite + `inputs` surface in skill-evals can be targeted
the same way; morning-brief was first because it is the biggest scheduled
token burner (p50 831K per live run).
