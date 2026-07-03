# skill-evals

Deterministic eval fixtures + checks for Edwin's skills. Skills grade themselves
today via honor-system self-checks inside their own prompts; this is the
mechanical layer that runs against the skill's ACTUAL outputs (artifacts +
Completion Reports) and catches regressions the moment a skill or model changes.
Companion to `tools/librarian`'s retrieval eval -- same `.eval-history.jsonl`
and regression-ALERT conventions. Frozen input fixtures are the prerequisite
for replayable optimization runs (GEPA).

Design follows the published patterns (philschmid.de/testing-skills, Tessl
skill-optimizer): deterministic boolean checks in a dispatch registry keyed by
check id; grade OUTCOMES (the artifact says X) not paths (the agent did Y);
no LLM-judge in v1.

## Usage

```bash
skill-evals check <skill> [--artifact PATH] [--report PATH] [--path-override ORIG=NEW] [--no-history]
skill-evals check-all          # default suite for every skill in docs/SKILLS.md + full suites
skill-evals fixtures freeze <skill>
skill-evals list               # check registry + existing suites
```

- Exit 0 = clean. Exit 2 = any FAIL or regression ALERT (Plombery non-ok
  signaling, same pattern as budget-watch). Scheduled daily 7:45 AM ET as
  `sys-skill-evals` (trigger t60), after the morning skill wave.
- `--no-history`: corruption tests and fixture replays should use this so they
  don't pollute the regression baseline.
- History: `.eval-history.jsonl`. Regression rule (matches
  `tools/librarian/lib/retrieval_eval.py`): a check that ever passed and has
  now failed 2 consecutive runs raises an ALERT line.

## Completion reports

Report-target checks read the newest file under
`data/skill-evals/reports/<skill>/`. The orchestrator (or the skill's runner)
should save each Completion Report there as `YYYY-MM-DD-HHMM.txt` after a run.
Until a report is captured, report checks SKIP -- they never fail on absence.

## Suites

`suites/<skill>.json`:

```json
{
  "skill": "name",
  "artifact_globs": ["briefing-book/docs/.../Artifact -- *.md"],
  "checks": [
    {"name": "unique-name", "check": "<registry id>", "target": "artifact|report|report_artifact|path", "params": {...}}
  ],
  "inputs": [
    {"glob": "data/o365/mail/{month}/*.md", "newest": 100}
  ]
}
```

- `artifact_globs` are relative to `$EDWIN_HOME`; the newest match (by mtime) is
  the artifact under test. List archive folders too -- the daily archiver moves
  artifacts.
- `target`: `artifact` (resolved artifact), `report` (captured Completion
  Report), `report_artifact` (the artifact the report CLAIMS -- used by the
  default suite), `path` (explicit `params.path`, e.g. a ledger or state file).
- `inputs` define the fixture-freeze surface: the files the SKILL.md reads.
  Placeholders: `{today}` `{yesterday}` `{month}` `{prev_month}`. `newest: N`
  samples the N most-recently-modified matches. Caps: 50MB per skill total,
  12MB per file (override per-input with `file_cap_bytes`). The manifest
  records sampled-vs-full and everything skipped.

Every skill in `docs/SKILLS.md` also gets the **default suite** automatically
(no file needed): completion report parses, STATUS valid
(success|partial|error), claimed ARTIFACT exists, and no em dashes / no
truncation markers in the claimed artifact.

## System-level suites

Any `suites/*.json` whose stem is NOT a skill in `docs/SKILLS.md` is a
**system-level suite**: `check-all` runs it after the per-skill pass (full
suite only -- there is no Completion Report to grade). `suites/system.json`
is the landing zone for self-retro corrections that are cross-skill or
infrastructure-shaped. Pattern: a producing tool computes the mechanical fact
as an ALERT line in its artifact (e.g. `tools/systems-report/report` emits
Plombery consecutive-failure streaks and expired staleness dismissals), and a
`regex_absent` check here turns that ALERT into exit-2 signal the daily
`sys-skill-evals` run cannot normalize away. A `file_fresh` check guards
against passing on a stale artifact.

## Adding a suite (the nightwatch pattern -- one skill per night)

1. Read the skill's SKILL.md. Note: artifact path + frontmatter contract,
   required sections and their order, page budget, list caps, any side files
   (state JSON, JSONL ledgers), the Completion Report fields, and any
   zero-result rule ("write NO file when empty").
2. Compose `suites/<skill>.json` from the registry (`skill-evals list`).
   Prefer structure checks (`sections_in_order`, `counts_equal`,
   `frontmatter_count_matches`) over content checks; every check must be
   deterministic and grade the outcome.
3. **Calibrate against a REAL, human-reviewed artifact**: `skill-evals check
   <skill>` must pass 100% legitimately. A check that fails on approved output
   is a bad check -- fix the check, not the artifact, and note why.
4. **Corruption-test**: copy the real artifact, seed one defect per check
   (wrong date, em dash, missing section, extra list item, bad enum...), and
   confirm `check <skill> --no-history --artifact <copy>` fails on exactly the
   intended check.
5. `skill-evals fixtures freeze <skill>` to snapshot today's inputs.
6. Keep thresholds honest: `max_lines` ~2-3x the current good artifact, list
   caps exactly what the SKILL.md mandates.

This registry is also where self-retro corrections land as permanent checks:
when a retro adopts a correction that is mechanically checkable ("no X in
artifacts", "always include section Y"), add it to the relevant suite (or
`suites/system.json` for cross-skill lessons) so the lesson can never
silently regress. The full pipeline (check > harness diff > prose memory,
plus the escalation ladder) is specified in
`skills/self-retro/SKILL.md` > Corrections Pipeline.

## Learning-loop data files

- `cases.jsonl` (this directory): one labeled case per graded self-retro
  correction -- `{date, rubric_line, failure, correction_form, ref, retro}`.
  The accumulating trainset for future GEPA/optimization runs. Append-only.
- `data/skill-evals/behavior-regression.jsonl`: one scenario case per past
  graded failure -- `{id, scenario, expected_behavior, source_failure,
  enforcement, added}`. The weekly self-retro re-scores every case against
  the week's evidence (PASS / FAIL / NOT-EXERCISED) and reports the gain
  line; a FAIL escalates the case's enforcement one rung (prose -> check ->
  hook). Append-only; `enforcement` is the only mutable field.

## Layout

```
skill-evals            the CLI (python3 stdlib only)
suites/<skill>.json    full check suites (morning-brief, pre-decision-brief,
                       decision-ledger, self-retro so far)
suites/system.json     system-level suite (cross-skill ratchet checks)
cases.jsonl            labeled self-retro correction cases (GEPA trainset)
fixtures/<skill>/<date>/manifest.json + tree/...   frozen input snapshots
.eval-history.jsonl    run history (regression baseline)
```
