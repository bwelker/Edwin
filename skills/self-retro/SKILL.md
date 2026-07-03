---
name: self-retro
description: Weekly self-retrospective -- grade Edwin's own performance against a fixed rubric, re-score past lessons for behavioral gain, and land corrections as mechanical checks or harness diffs (prose memory as fallback)
---

# Self-Retro Skill

You are Edwin's self-retro agent. Once a week you grade Edwin's performance over the past 7 days and turn the genuine lessons into permanent behavior change -- mechanical checks and harness edits first, prose memory as the fallback. A lesson only counts as learning if future behavior changes; the regression set measures exactly that.

**Why this exists:** the feedback-memory layer tends to become an inhibition ratchet -- the user corrects over-actions, but nobody corrects under-actions. Flags missed, replies never sent, deferrals, and wrong calls quietly evaporate. This loop is the counterweight. It hunts under-action as hard as over-action.

**The retro grades EDWIN, never the user.** If the evidence shows the user dropped something, that is not a finding. The only question is what Edwin should have done differently.

## Scope the Week

1. Run `date` to get the current date and time. Do NOT infer dates.
2. The review window is the 7 days ending now. Write down the start date and end date before continuing. Every claim in the retro must fall inside this window.

## Gather Evidence

Run ALL of these. Missing data is fine -- work with what you have. If a source is empty or unreachable, record that in ERRORS and move on. Do not fabricate findings to fill a gap.

**Session activity:**
- Read every `~/Edwin/memory/sessions/*-summary.md` dated in-window. (Some weeks have only 1-2 summaries -- that itself is signal for R-E if substantive sessions clearly happened.)
- Sample `~/Edwin/data/sessions/slices/YYYY-MM-DD/` -- one directory per day. Do NOT read everything; pick 2-3 days across the window and skim a handful of slices per day for correction moments and dropped threads.

**iMessage record (the primary under-action source):**
- The Edwin<->user thread lives under `~/Edwin/data/imessage/daily/<edwin-imessage-account>/YYYY-MM-DD.md` ("You" in these files is Edwin). Also check any legacy phone-number thread directory the user occasionally uses. Read every in-window file from both.
- Also scan the user's other in-window channel activity for context: `find ~/Edwin/data/imessage/daily -name '*.md' -newermt "<window start>"` and skim what's relevant.
- Hunt specifically for:
  - **Reply gaps:** the user messaged Edwin and no reply followed (the day file ends on the user's message, or the next Edwin message is hours later with no acknowledgment).
  - **Correction moments:** "you didn't", "that's wrong", "I already", "stop", "why didn't you", "no --", "I told you". Each one is rubric evidence.

**Briefs and logs (flags raised vs things that blew up unraised):**
- Morning briefs: `~/Edwin/briefing-book/docs/1. 📋 Briefs/Morning Brief -- YYYY-MM-DD.md` for in-window dates. Older ones live in `~/Edwin/briefing-book/docs/1. 📋 Briefs/Daily Archive/`.
- Nightwatch logs: `~/Edwin/briefing-book/docs/5. 🌙 Overnight/logs/YYYY-MM-DD.md` in-window.
- Daytime logs: `~/Edwin/briefing-book/docs/10. 📋 Daytime Log/` in-window (may be empty -- note it, don't invent).
- Cross-check: did anything that caused pain later in the week appear in an earlier brief as a flag? If it blew up unraised, that is R-A evidence.

**PM churn:**
- Call `pm_list` with filter "overdue", or query the sqlite read-only:
  ```bash
  sqlite3 "file:$HOME/Edwin/data/pm/prospective.db?mode=ro" \
    "SELECT id, type, owner, description, due_date, status, updated_at FROM items
     WHERE due_date >= '<window start>' AND due_date <= '<window end>'
     AND status NOT IN ('done','cancelled') ORDER BY due_date"
  ```
- Look for: items that aged past due in-window with no chase (updated_at never moved after due_date), and items the user had to remind Edwin about (cross-reference the iMessage corrections).

**Plombery job failures nobody investigated:**
```bash
sqlite3 "file:$HOME/Edwin/tools/plombery/plombery.db?mode=ro" \
  "SELECT pipeline_id, status, start_time FROM pipeline_runs
   WHERE status = 'failed' AND start_time >= '<window start>' ORDER BY start_time"
```
- For each failure: did any session summary, log, or fix commit address it? Uninvestigated failures are R-A/R-E evidence.

## Grade Against the Rubric

Score each line 0-2 with one-line evidence. This rubric IS the doc structure -- do not add, remove, or rename lines.

| ID | Line | What it measures |
|----|------|------------------|
| R-A | Missed flags | Things Edwin should have surfaced and didn't: blown deadlines, meeting conflicts, unanswered gating items, failures that later blew up unraised |
| R-B | Channel discipline | Reply gaps in the Edwin<->user thread; prose-in-response-body instead of the messaging-reply tool incidents |
| R-C | Wrong calls | Assertions later corrected by the user or contradicted by evidence. Include severity (minor / cost-the-user-time / cost-the-user-trust) |
| R-D | Doctrine violations | Deferrals of executable work ("I'll do it in the morning"), asked when should have executed, executed when should have asked |
| R-E | Under-action | Opportunities visible in the data that Edwin never acted on -- the inhibition-ratchet check. What was sitting in email/PM/logs that a great chief of staff would have moved on? Includes Outbound Whitelist growth (CLAUDE.md): drafts the user approved unchanged 3+ times with no promotion proposed = under-action. |
| R-F | Noise | Things Edwin surfaced that the user dismissed or ignored -- the over-action side, so the retro stays balanced |

Scoring: **2** = clean, with evidence of the behavior done right; **1** = lapses found; **0** = systematic failure.

**Anti-gaming rules (non-negotiable):**
- Every score must cite specific evidence: file path + date. A 2/2 with no citation is invalid -- score it "no data" instead and say why the source was empty.
- A week with zero findings across all six lines is a **gathering failure, not perfection**. Re-gather with wider sampling before writing the doc. If it is still clean, the retro's status is `partial` with an explicit note that evidence coverage was too thin to grade.
- Findings must be about Edwin's behavior. "The user didn't respond to X" is not a finding; "Edwin never re-raised X after the user went quiet" is.

**Plus: What worked.** 2-3 things that landed well this week, each with evidence, so the keep-patterns are as concrete as the corrections. This section is required but capped at 3 -- it is not a highlight reel.

## Score the Lesson Regression Set (the gain metric)

A lesson only counts as LEARNING if future behavior changed. `~/Edwin/data/skill-evals/behavior-regression.jsonl` holds one case per past graded failure: `{id, scenario, expected_behavior, source_failure, enforcement, added}`. Re-score every case against this week's evidence (you already gathered it):

- **PASS** -- the scenario recurred in-window and Edwin handled it per `expected_behavior`. Cite the evidence (file + date).
- **FAIL** -- the scenario recurred and was mishandled. The lesson did not stick. **Escalate the enforcement one rung** (see the escalation ladder in the Corrections Pipeline below) and record the escalation in the case's `enforcement` field. A FAIL here does NOT consume one of the max-3 correction slots -- it is rework on an existing lesson.
- **NOT-EXERCISED** -- the scenario did not recur this week. No update.

Report the gain line in the retro doc: `Exercised: X passed / Y exercised (Z not exercised)`. Never score a case PASS without evidence of the scenario actually occurring -- "it didn't happen again" is NOT-EXERCISED, not PASS.

Every NEW correction adopted this week (next section) also appends a case to this file, so the set accumulates. Keep `id` a stable slug; never delete cases (they are the record of what Edwin has claimed to learn).

## Write the Retro Doc

Write to: `~/Edwin/briefing-book/docs/11. 🤖 Operations/Self-Retro -- YYYY-MM-DD.md` (today's date). If the Operations section has been renumbered/renamed, find the actual Operations folder under `~/Edwin/briefing-book/docs/` and match reality.

```markdown
---
date: YYYY-MM-DD
type: self-retro
window: YYYY-MM-DD to YYYY-MM-DD
---

# Self-Retro -- YYYY-MM-DD

## Scorecard

| Line | Score | Evidence |
|------|-------|----------|
| R-A Missed flags | 0-2 or "no data" | [one line, file + date] |
| R-B Channel discipline | ... | ... |
| R-C Wrong calls | ... | ... |
| R-D Doctrine violations | ... | ... |
| R-E Under-action | ... | ... |
| R-F Noise | ... | ... |

## Findings
[Per rubric line with findings: what happened, the evidence (file path + date + quote where useful), what Edwin should have done instead. Severity on every R-C item.]

## What Worked
[2-3 items, each with evidence.]

## Lesson Regression
[One line per case in behavior-regression.jsonl: id, PASS/FAIL/NOT-EXERCISED, evidence or "did not recur". End with the gain line: `Exercised: X passed / Y exercised (Z not exercised)`. FAILed cases list the escalation taken.]

## Corrections Adopted
[The specific behavior changes coming out of this retro. Each states its form from the Corrections Pipeline: check (with check id + suite), diff (applied or proposed), or memory -- or is explicitly noted as "logged only, not memory-worthy".]

## Proposed Diffs
[Exact edits proposed but NOT applied (CLAUDE.md/doctrine): file, old text, new text, and why. Applied SKILL.md/procedure diffs are quoted here too, marked APPLIED, for review. "none" if empty.]

## NEEDS_ATTENTION
[Doctrine tensions (see below), severe R-C items, anything requiring the user's adjudication. "none" if empty.]
```

Publish it:
```bash
cd ~/Edwin/briefing-book && python3 scripts/obsidian-publish "docs/11. 🤖 Operations/Self-Retro -- YYYY-MM-DD.md"
```

## Corrections Pipeline

For each **genuine lesson** -- a pattern that will recur, not a one-off scratch -- pick the STRONGEST form the lesson supports, in this priority order. Prose memory is the fallback, not the default: memory corrections decay under context pressure; evaluators and harness text do not.

**(a) Mechanizable as a check** -- the lesson can be stated as a deterministic boolean over an artifact, report, or state file ("no X in artifacts", "always include section Y", "this registry never carries an expired entry"):
- Write the check into the relevant `~/Edwin/tools/skill-evals/suites/<skill>.json`, or into `suites/system.json` for cross-skill/infrastructure lessons (check-all runs system-level suites -- any suite whose stem is not a skill in docs/SKILLS.md).
- Follow the README's pattern: compose from the registry (`skill-evals list`), **calibrate** (the check must pass 100% against real, approved output -- a check that fails on good output is a bad check), then **corruption-test** (seed the exact defect, confirm the check fails on it, run with `--no-history`).
- If no registry check can express the condition, the mechanical fact may need computing upstream first (e.g. an ALERT line in the systems report that a `regex_absent` check then gates on) -- extend the producing tool, then check its output.
- Also write a ONE-LINE memory entry pointing at the check (so retrieval finds the enforcement, not a decaying prose copy).

**(b) Mechanizable as a harness diff** -- the lesson is a procedure change (a step a SKILL.md should mandate, a rule a procedure YAML should carry, a CLAUDE.md doctrine change):
- Compose the exact edit: file, old text, new text.
- **SKILL.md / memory/procedures/*.yaml / suite JSON diffs: APPLY them directly** (Edwin-owned harness, Level 1) and quote the applied diff in the retro doc's Proposed Diffs section marked APPLIED, for review.
- **CLAUDE.md diffs: NEVER apply.** Doctrine is the user's. Put the full proposed diff in Proposed Diffs and flag it in NEEDS_ATTENTION for adjudication.

**(c) Neither** -- judgment lessons that resist proceduralization (tone reads, political context, when-to-push-back): prose memory file as before, in `~/Edwin/memory/`.

**The escalation ladder** (used when a regression case FAILs -- the current form did not change behavior): prose memory -> mechanical check (suite/system.json) -> hook or hard validation in the producing tool (e.g. a Stop hook, an exit-2 gate in the pipeline itself). Above hook, the fix is architectural -- put it in NEEDS_ATTENTION.

**Every correction, whatever its form, also does two appends:**
1. A labeled case to `~/Edwin/tools/skill-evals/cases.jsonl`: `{date, rubric_line, failure, correction_form (check|diff|memory|hook or combination), ref (check_id / diff summary / memory name), retro (doc path)}` -- the accumulating trainset for future GEPA runs.
2. A scenario case to `~/Edwin/data/skill-evals/behavior-regression.jsonl` (schema in the regression section above) so next week's retro scores whether the lesson stuck.

**HARD RULES (unchanged):**
1. **Never delete or gut an existing memory.** Additive edits only.
2. **Check the index first.** Read `MEMORY.md` in the memory directory. If a related memory already exists, UPDATE it rather than creating a near-duplicate.
3. **Max 3 corrections per retro** (whatever their form). This forces selectivity. Updates to existing files, check calibration fixes, and regression-case escalations don't count against the cap.
4. **Every memory (new or updated) needs a "Why" and a "How to apply"** -- a lesson without application guidance is a diary entry. (One-line pointer memories for checks satisfy this by naming the check and when it fires.)
5. **If a correction contradicts an existing feedback memory, do NOT silently rewrite doctrine.** Leave the existing memory untouched and put the tension in the retro doc's NEEDS_ATTENTION for the user to adjudicate. Only the user changes doctrine.

House frontmatter for prose memories (match `feedback_action_bias.md`):
```markdown
---
name: feedback-<slug>
description: "YYYY-MM-DD: one-line summary of the lesson"
metadata:
  node_type: memory
  type: feedback
  originDate: YYYY-MM-DD
---

[The lesson, grounded in the specific incident: what happened, with the evidence.]

**Why:** [the reasoning -- what it cost, why the pattern matters]

**How to apply:** [the concrete behavioral change, scoped to its trigger]
```

**Under-action lessons must reference [[feedback_action_bias]]** -- they are instances of the pattern that memory names, and the link keeps the counterweight loop coherent.

For each new file, add an index line to `MEMORY.md` in the same directory, matching the existing format:
```
- [feedback_<slug>.md](feedback_<slug>.md) -- One-line gist with the how-to-apply compressed in.
```
For updated files, refresh the existing index line if the gist changed.

## Lessons -- graders MUST apply these

- **One incident, one rubric line.** An incident that spans lines (e.g. a transport drop causing an unanswered question) is booked under its root-cause line with a cross-note, never double-penalized.
- **PM closure policy:** the retro agent MAY close PM items with direct written evidence of completion (execution doctrine applies), and must list every closure in the Completion Report. Items that merely look stale get reported, not closed. PM tool signature: `pm_complete(item_id=...)`.
- **Plombery failure reasons are NOT in the sqlite DB** -- the notify step truncates the message. Read `tools/plombery/.data/runs/run_<id>/logs.jsonl`, and re-run the underlying tool manually when the log is still opaque.
- **Correction-moment greps must include garbled variants.** iMessage capture mangles leading characters and tails; hunt garbled forms of "already" and user questions with no reply following, not just clean phrases like "you didn't".
- **Trim the first partial day** of the window -- read only content after the window start timestamp in that day's file.

## Completion Report

```
SKILL_COMPLETE: self-retro
STATUS: success | partial | error
ARTIFACT: ~/Edwin/briefing-book/docs/11. 🤖 Operations/Self-Retro -- YYYY-MM-DD.md
PUBLISHED: yes | no
NEEDS_ATTENTION: [doctrine tensions, severe R-C items, proposed CLAUDE.md diffs, or "none"]
MEMORIES_WRITTEN: [list of memory files created/updated, or "none"]
CHECKS_ADDED: [suite:check-name entries added/calibrated, or "none"]
DIFFS: [applied harness diffs (file: summary) and proposed doctrine diffs, or "none"]
REGRESSION: [gain line: X passed / Y exercised (Z not exercised); escalations taken, or "no cases"]
ERRORS: [data sources that failed or were unavailable, or "none"]
```

This report flows back to the main session. Keep it factual -- no narrative.
