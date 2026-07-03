# skill-retirement

Ablation test for whether a skill earns its keep (Memory Upgrade Backlog item
A11 #3: "run evals with the skill unloaded; if pass rates hold, retire it").

Built ON the existing eval stack, not a reinvention:

- `tools/skill-gepa/run_skill_on_fixtures.py` -- sandboxed skill runner (frozen
  fixture day, headless Haiku, no MCP/hooks). Reused verbatim as a subprocess.
- `tools/skill-gepa/metric.py` -- scores an artifact with the skill's
  skill-evals suite (pass fraction). Reused for both arms.
- `tools/skill-evals/suites/<skill>.json` -- the graded contract + the
  `artifact_globs` used to resolve a produced artifact for any skill (the
  gepa runner only natively resolves morning-brief's).

## The test

```
BASELINE = runner(live SKILL.md) -> suite score      (reuse a prior run via
                                                      --baseline-result to
                                                      avoid paying twice)
ABLATED  = runner(stub SKILL.md) -> suite score       (skill "unloaded")
VERDICT  = ablated >= baseline - tolerance ? RETIREMENT_CANDIDATE : KEEP
```

The **stub** preserves the YAML frontmatter (name + description = the
always-loaded trigger) and replaces the entire body with a single
check-agnostic directive that states only the goal. It never mentions anything
the eval checks look for (no "no em dashes", no required sections) -- baking
check hints into the ablation would bias toward false retirement. `show-stub`
prints it without running.

If the ablated run can't produce an artifact at the skill's contract path, the
body is load-bearing -> KEEP (it encodes the publish location/naming/date the
suite grades).

## Usage

```bash
skill-retirement test <skill> [--baseline-result PATH] [--tolerance 0.05] \
    [--fixture-date D] [--model M] [--max-turns N] [--stub PATH] [--json]
skill-retirement show-stub <skill>
```

Records append to `retirement-history.jsonl` (skill, fixture day, both scores,
delta, verdict, cost). Sandboxes land under
`tools/skill-gepa/runs/retirement/` (gitignored).

## Caveat

One fixture day on Haiku is proof-of-life thin (same limit as skill-gepa): with
a single day a "held pass rate" could be that day's data, not a dead skill.
Want >=3 frozen days and/or multiple seeds before actually retiring anything.
The harness reports the evidence; retiring a skill is the operator's/
orchestrator's call. Nothing here mutates a live skill.

## Verified

morning-brief, fixture 2026-07-02, reusing the $0.28 baseline (10/11): the
ablated run wrote a brief but to `docs/2026-07-03-morning-brief.md` with the
wrong naming and today's date instead of the frozen date, so the contract
globs matched nothing. Verdict **KEEP** -- the body carries the publish
contract. Ablated run cost ~$0.17.
