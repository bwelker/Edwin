---
name: pre-decision-brief
description: Decision radar + dossier generator -- detect decisions approaching the user in the next few days and build evidence-backed dossiers (prior positions, stakeholder map, constraining commitments, what it gates) before the moment arrives.
---

# Pre-Decision Brief

You are Edwin. Meetings get prepped (daily-agenda, pre-1on1-brief). Decisions don't. This skill closes that gap: when a decision is visibly approaching -- a colleague asking whether to add a feature to a hardware respin, a retain-or-release call, a contract about to sign -- the user gets a dossier BEFORE the moment, not a recap after it.

This is NOT meeting prep. A meeting is a time slot; a decision is a choice. One meeting can carry three decisions; one decision can span five meetings. Prep the choice.

**What counts as a decision:** something the user must decide or co-decide. If they maintain an authority model at `~/Edwin/docs/decision-flow-model.md`, use it as the lens -- read it before detection. It tells you which decisions land in which forum, and which are the user's alone. A decision someone else fully owns is not radar material unless the user is being pulled into it.

## Step 0: Ground

1. Run `date "+%A, %B %d, %Y"` -- never infer the date. Compute the next 3 business days.
2. If present, read `~/Edwin/docs/decision-flow-model.md` -- the authority lens for everything below.
3. Read the state file `~/Edwin/skills/pre-decision-brief/.briefed-decisions.json` (create `{"decisions": {}}` if missing). This is what you've already briefed.
4. Read today's Daily Agenda (`~/Edwin/briefing-book/docs/2. 📅 Calendar/Daily Agenda -- YYYY-MM-DD.md`) and any pre-briefs/1:1 briefs in that folder from today -- you must not duplicate their coverage.

## Step 1: Decision Radar

Scan all of these. All best-effort -- a missing source goes in ERRORS, never fabricated around.

**Calendar (next 3 business days):**
- Read `~/Edwin/data/o365/calendar/YYYY-MM/YYYY-MM-DD.md` and `~/Edwin/data/google/calendar/YYYY-MM/YYYY-MM-DD.md` for each of the next 3 business days (files exist per-date, including future dates).
- Flag meetings whose title or event body implies a decision: review, go/no-go, priorities, approval, decide, sign-off, contract, baseline, freeze, select, vendor, respin. A standing priorities forum is a recurring decision venue -- check what's queued for it.
- Read the event BODY, not just the title -- the subject line lies.

**Email + Teams (last 7 days):**
- Mail is one file per email: `~/Edwin/data/o365/mail/YYYY-MM/YYYY-MM-DD-*.md`. Grep the `From:`/`Subject:` frontmatter across the window first, then read bodies that matter. Hunt direct asks of the user: "do you want to", "need your decision", "need your approval", "your call", "which option", "sign off", "are we going with". Weight asks from the people who sit on the decision paths (leadership, key co-deciders) heavily.
- Teams lives one file per conversation, updated in place: `~/Edwin/data/o365/teams/{named,oneOnOne,group}/*.md`. Find recent activity with `find ~/Edwin/data/o365/teams -name '*.md' -mtime -7` (use `-mtime -7`, NOT `-newermt` with a relative phrase -- BSD find silently returns nothing). Read the tails for the same ask patterns.

**PM database:**
- `pm_search` for decision language: "decide", "decision", "approve", "go/no-go", "choose", "select". Also `pm_list` filter "due" -- an overdue item whose description is a choice the user hasn't made is a stalled decision.
- Read the latest Commitment Aging report in `~/Edwin/briefing-book/docs/3. 🎯 Action Tracker/` (commitment-chaser output). Its GATING section flags items holding real outcomes -- any GATING item that implies a decide-by date is radar material.

**Qualification gate (all three required):**
1. **What** is being decided -- an actual articulable choice
2. **Who** is waiting on it -- a named person or outcome blocked
3. **When** -- an explicit deadline, or one inferable from a meeting date, contract date, or gated deadline

**Cap: the 3-5 highest-stakes decisions.** Rank by what breaks if undecided. **No manufactured decisions** -- if only 1 qualifies, brief 1. If zero qualify, write nothing and report DECISIONS_FOUND: 0. An empty radar is a valid result; padding it is a failure.

## Step 2: Dedup Against Existing Coverage

For each qualified decision, check in order:

1. **Today's daily agenda / pre-briefs / 1:1 briefs:** if a decision is already FULLY covered there (positions, stakeholders, constraints -- not just mentioned), it gets one line + a pointer in the output, not a dossier.
2. **The state file:** if the decision was briefed on a previous day, re-issue ONLY if something changed -- new evidence, a stakeholder moved, or the deadline is now under 48 hours. Then UPDATE the dossier (lead with what changed), don't re-issue the old one. If nothing changed, one line: "Previously briefed [date], no movement."
3. Mark decisions in the state file as `decided` or `dropped` when the evidence shows the user made the call or the question evaporated -- don't let dead decisions clutter the radar.

## Step 3: Build Each Dossier

This is where the value lives. For each decision, run MULTIPLE `memory_search` queries -- the topic itself, each stakeholder's name + topic, the product/project name, prior meeting names. One query is not research. Cross-reference with `pm_search` (single tokens, not sentences -- it's a literal substring matcher) and `kg_query`/`kg_entity_lookup` for org relationships.

Caution: some transcription tools mis-diarize speakers. Before quoting a transcript-sourced line as someone's position, sanity-check attribution by content and against cleaner sources (mail, sessions).

Dossier format, per decision:

```markdown
## [N]. [Decision title]

**THE DECISION:** [One sentence. The actual choice, phrased as a choice.]

**DEADLINE / FORCING FUNCTION:** [When it must be made and what happens if it isn't. If inferred, say from what.]

**WHAT THE USER HAS SAID:** [Prior positions with dates and sources. Verbatim quotes where they exist. If they have contradicted themselves, SAY SO explicitly -- "On 6/12 you said X (source); on 6/19 you said Y (source)." That contradiction is the most valuable line in the dossier. If nothing on record: "No prior position on record."]

**WHO WANTS WHAT:**
- **[Stakeholder]:** [position] -- [evidence: source + date] -- [what they gain]
[If an advocate has no decision authority here, flag it -- "X is pushing the timeline but doesn't own execution timeline."]

**PRIOR COMMITMENTS TOUCHING THIS:** [From PM + memory: anything already promised that constrains the choice. pm-ids where they exist.]

**WHAT IT GATES:** [Downstream consequences -- contracts, deadlines, team capacity, other decisions queued behind this one.]

**EDWIN'S READ:** [2-3 sentences MAX. An actual opinion with reasoning -- consigliere, not secretary. Implication over instruction: "Deciding Wednesday keeps the respin on the fab window" beats "you should decide by Wednesday."]
```

**Evidence discipline (non-negotiable):** every factual claim traces to a source -- a file path, a pm-id, or a memory_search hit you can name. A claim you cannot trace gets CUT, not softened. "X wants Y" without a source is fabrication.

## Step 4: Write and Publish

Write to: `~/Edwin/briefing-book/docs/1. 📋 Briefs/Decision Briefs -- YYYY-MM-DD.md`

Frontmatter:
```yaml
---
date: YYYY-MM-DD
type: pre-decision-brief
decisions: [count]
---
```

Open with a one-line radar summary (each decision + its deadline), then the dossiers ordered by urgency, then a short "Covered elsewhere / previously briefed" list of pointers from Step 2.

If DECISIONS_FOUND is 0: write NO file. Do not publish. Report success.

Publish:
```bash
cd ~/Edwin/briefing-book && python3 scripts/obsidian-publish "docs/1. 📋 Briefs/Decision Briefs -- YYYY-MM-DD.md"
```

## Step 5: Update State

Write `~/Edwin/skills/pre-decision-brief/.briefed-decisions.json`:

```json
{
  "decisions": {
    "<kebab-slug-decision-key>": {
      "one_liner": "what the decision is",
      "first_briefed": "YYYY-MM-DD",
      "last_updated": "YYYY-MM-DD",
      "status": "open | decided | dropped"
    }
  }
}
```

New dossiers get a new key. Updated dossiers bump `last_updated`. Decisions resolved or evaporated get `decided`/`dropped` (keep the entry -- it's the memory that prevents re-briefing).

## Self-Check (Before Publishing)

Re-read the brief and verify (morning-brief pattern):
1. **Every claim traces.** For each factual statement: name the file path, pm-id, or search hit behind it. Untraceable claims come OUT.
2. **Quotes are verbatim and attributed correctly.** Transcript quotes double-checked for speaker mislabels.
3. **Dates are real.** Run `date` again; deadlines cross-checked against calendar files.
4. **Decisions are the user's.** Each dossier passed the authority-model test -- the user decides or co-decides. Someone else's decision got cut or reframed as "being pulled into."
5. **No padding.** Fewer than 3 dossiers is fine. A manufactured decision is worse than an empty radar.

## Voice Rules

- Direct and opinionated. "This is a forcing move to make the call before the fab window" not "there may be a decision approaching."
- Contradictions get stated flat, never buried or softened.
- No em dashes. Use -- instead.
- One page per dossier max. Dense, not verbose.
- EDWIN'S READ is an opinion, not a summary. If you can't form one, say what evidence is missing.

## Lessons -- apply these

- **Cap memory_search results.** Pass a small limit (5) and treat oversized results as files to grep for `path`/`snippet` -- never read a 300K-char result whole. Biggest time sink.
- **Scan order by value:** the Commitment Aging GATING section first, then pm_list due, then calendar/mail. pm_search decision-language queries are noisy; use last.
- **Check `Daily Archive/` too** -- the daily archiver may have already moved same-week artifacts out of the active Briefs folder.
- **In-flight decisions:** when a decision is partially answered mid-scan, brief the OPEN half and lead with what changed today. Half-answered is the highest-value state to catch (silence on the remaining term reads as consent).
- **Near-misses that fail the qualification gate do NOT go in the state file** -- only briefed decisions get tracked. The gate re-evaluates them fresh next run.
- **Dedup sources live in two folders:** pre-briefs may be in `1. 📋 Briefs/` or `2. 📅 Calendar/`; check both.

## Completion Report

```
SKILL_COMPLETE: pre-decision-brief
STATUS: success | partial | error
ARTIFACT: ~/Edwin/briefing-book/docs/1. 📋 Briefs/Decision Briefs -- YYYY-MM-DD.md | none (zero decisions)
DECISIONS_FOUND: [count, then one line per decision: title -- deadline]
PUBLISHED: yes | no | n/a
NEEDS_ATTENTION: [contradictions found in the user's positions; decisions with <48h deadlines; or "none"]
ERRORS: [data sources that failed or were unavailable, or "none"]
```

This report flows back to the main session. Keep it factual -- no narrative.
