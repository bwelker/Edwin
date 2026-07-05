#!/usr/bin/env python3
"""Tests for tools/dispatch/dispatch.

Each test runs against a throwaway nightwatch dir + skills dir with the
clock pinned via EDWIN_DISPATCH_NOW. All plan fixtures are synthetic and
written inline.

Run: python3 tools/dispatch/tests/run_tests.py
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
DISPATCH = HERE.parent / "dispatch"
TZ = ZoneInfo("America/New_York")

loader = importlib.machinery.SourceFileLoader("dispatch_mod", str(DISPATCH))
spec = importlib.util.spec_from_loader("dispatch_mod", loader)
dispatch = importlib.util.module_from_spec(spec)
loader.exec_module(dispatch)

# A "tonight" anchor: nightwatch started 21:00, heartbeat at 23:00.
NIGHT = datetime(2026, 7, 1, 23, 0, tzinfo=TZ)
PLAN_DATE = "2026-07-01"

FRESH_PLAN = """---
date: 2026-07-01
type: nightwatch-plan
---

# Nightwatch Plan -- 2026-07-01

## Assessment Summary
Some prose. A bullet that is not a task:
- **HARD FENCE** stays off-limits.

## Group 1 (parallel)
- [ ] 1. First task alpha | operator | S | why-a
- [ ] 2. Second task beta | architect | M | why-b

## Group 2 (after group 1)
- [ ] 3. Third task gamma | operator | S | why-c

## Notes for the orchestrator
- Time gate: run date before each task.
"""

MID_GROUP_PLAN = FRESH_PLAN.replace(
    "- [ ] 1. First task alpha", "- [x] 1. First task alpha").replace(
    "why-a\n", "why-a\n  - RESULT (21:15): done, all clean.\n")

GROUP1_DONE_PLAN = MID_GROUP_PLAN.replace(
    "- [ ] 2. Second task beta", "- [x] 2. Second task beta")

EXHAUSTED_PLAN = GROUP1_DONE_PLAN.replace(
    "- [ ] 3. Third task gamma", "- [x] 3. Third task gamma")

MALFORMED_PLAN = """# Plan

## Group 1 (parallel)
- [ ] 1. Good task one
-[ ] 2. Missing space after dash
- [] 3. Empty box means unchecked
* [ ] 4. Star bullet task
- [X] 5. Capital X checked
  - [ ] indented sub-checklist item is NOT a task
  - RESULT (01:00): result line for something.
- not a task at all, plain bullet
"""


def write_state(nw_dir: Path, active=True, stop_at=None, started_at=None):
    state = {
        "active": active,
        "stop_at": stop_at or "2026-07-02T03:30:00-04:00",
        "started_at": started_at or "2026-07-01T21:00:00-04:00",
        "trigger": "scheduled",
    }
    (nw_dir / ".nightwatch-state.json").write_text(json.dumps(state))
    return state


class DispatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="dispatch-test-")
        self.nw = Path(self.tmp) / "nightwatch"
        self.skills = Path(self.tmp) / "skills"
        self.nw.mkdir(parents=True)
        (self.skills / "morning-brief").mkdir(parents=True)
        (self.skills / "morning-brief" / "SKILL.md").write_text("# skill")
        (self.skills / "overnight-loop").mkdir(parents=True)
        (self.skills / "overnight-loop" / "SKILL.md").write_text("# planner")
        os.symlink(self.skills / "overnight-loop", self.skills / "nightwatch")
        os.environ["EDWIN_NIGHTWATCH_DIR"] = str(self.nw)
        os.environ["EDWIN_SKILLS_DIR"] = str(self.skills)
        self.set_now(NIGHT)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        for k in ("EDWIN_NIGHTWATCH_DIR", "EDWIN_SKILLS_DIR",
                  "EDWIN_DISPATCH_NOW"):
            os.environ.pop(k, None)

    def set_now(self, dt: datetime):
        os.environ["EDWIN_DISPATCH_NOW"] = dt.isoformat()

    def write_plan(self, text: str, date=PLAN_DATE):
        (self.nw / f"{date}-plan.md").write_text(text)

    def write_outcomes(self, entries, date=PLAN_DATE):
        out_dir = self.nw / "outcomes"
        out_dir.mkdir(exist_ok=True)
        (out_dir / f"{date}.jsonl").write_text(
            "".join(json.dumps(e) + "\n" for e in entries))

    def hb(self):
        return dispatch.run(["nightwatch_heartbeat"])

    def ack(self, rid, status, note=None):
        argv = ["ack", "--id", rid, "--status", status]
        if note:
            argv += ["--note", note]
        return dispatch.run(argv)

    # ---- run_skill -----------------------------------------------------

    def test_run_skill_valid(self):
        out = dispatch.run(["run_skill", "--skill", "morning-brief"])
        self.assertEqual(out["action"], "spawn")
        self.assertTrue(out["background"])
        self.assertEqual(out["label"], "skill:morning-brief")
        self.assertIn("skills/morning-brief/SKILL.md", out["prompt"])
        self.assertIn("Completion Report", out["prompt"])
        self.assertIn("Token budget", out["prompt"])
        self.assertTrue(out["on_complete"]["relay_needs_attention"])
        self.assertTrue(out["on_complete"]["investigate_on_error"])
        self.assertTrue(out["dispatch_id"].startswith("d-"))

    def test_run_skill_symlink(self):
        out = dispatch.run(["run_skill", "--skill", "nightwatch"])
        self.assertEqual(out["action"], "spawn")

    def test_run_skill_unknown(self):
        out = dispatch.run(["run_skill", "--skill", "no-such-skill"])
        self.assertEqual(out["action"], "report_error")
        self.assertIn("no-such-skill", out["message"])

    def test_run_skill_traversal_rejected(self):
        out = dispatch.run(["run_skill", "--skill", "../evil"])
        self.assertEqual(out["action"], "report_error")

    # ---- heartbeat: state gates ----------------------------------------

    def test_state_missing_noop(self):
        out = self.hb()
        self.assertEqual(out["action"], "noop")
        self.assertIn("inactive", out["reason"])

    def test_state_inactive_noop(self):
        write_state(self.nw, active=False)
        self.assertEqual(self.hb()["action"], "noop")

    def test_past_stop_at_winddown_once(self):
        write_state(self.nw, stop_at="2026-07-01T22:00:00-04:00")
        out = self.hb()
        self.assertEqual(out["action"], "log_winddown")
        # second heartbeat: already logged -> noop
        out2 = self.hb()
        self.assertEqual(out2["action"], "noop")
        self.assertIn("already wound down", out2["reason"])

    def test_past_330_gate(self):
        write_state(self.nw, stop_at="2026-07-02T06:00:00-04:00")
        self.set_now(datetime(2026, 7, 2, 3, 45, tzinfo=TZ))
        self.write_plan(FRESH_PLAN)
        self.assertEqual(self.hb()["action"], "log_winddown")

    def test_evening_not_blocked_by_330_gate(self):
        # 23:00 is not "past 3:30 AM" in the wind-down sense
        write_state(self.nw)
        self.write_plan(FRESH_PLAN)
        self.assertEqual(self.hb()["action"], "spawn_tasks")

    def test_missing_stop_at_winds_down(self):
        (self.nw / ".nightwatch-state.json").write_text(
            json.dumps({"active": True, "started_at": "2026-07-01T21:00:00-04:00"}))
        self.assertEqual(self.hb()["action"], "log_winddown")

    # ---- heartbeat: plan states ----------------------------------------

    def test_plan_missing_spawns_planner(self):
        write_state(self.nw)
        out = self.hb()
        self.assertEqual(out["action"], "spawn_planner")
        self.assertIn("PLANNER", out["prompt"])
        self.assertIn(PLAN_DATE + "-plan.md", out["prompt"])
        self.assertIn("Token budget", out["prompt"])

    def test_fresh_plan_spawns_all_group1(self):
        write_state(self.nw)
        self.write_plan(FRESH_PLAN)
        out = self.hb()
        self.assertEqual(out["action"], "spawn_tasks")
        self.assertIn("Group 1", out["group"])
        texts = [t["text"] for t in out["tasks"]]
        self.assertEqual(len(texts), 2)
        self.assertIn("First task alpha", texts[0])
        self.assertIn("Second task beta", texts[1])
        for t in out["tasks"]:
            self.assertIn("Execute this nightwatch task:", t["prompt"])
            self.assertIn("- [ ]` to `- [x]", t["prompt"])
            self.assertIn("overnight log", t["prompt"])
            self.assertIn("Token budget", t["prompt"])
            self.assertIn("EXECUTOR of this ONE task only", t["prompt"])

    def test_mid_group_partial_spawns_only_unchecked(self):
        write_state(self.nw)
        self.write_plan(MID_GROUP_PLAN)
        out = self.hb()
        self.assertEqual(out["action"], "spawn_tasks")
        self.assertEqual(len(out["tasks"]), 1)
        self.assertIn("Second task beta", out["tasks"][0]["text"])

    def test_group1_done_moves_to_group2(self):
        write_state(self.nw)
        self.write_plan(GROUP1_DONE_PLAN)
        out = self.hb()
        self.assertEqual(out["action"], "spawn_tasks")
        self.assertIn("Group 2", out["group"])
        self.assertIn("Third task gamma", out["tasks"][0]["text"])

    def test_exhausted_plan_spawns_replanner(self):
        write_state(self.nw)
        self.write_plan(EXHAUSTED_PLAN)
        out = self.hb()
        self.assertEqual(out["action"], "spawn_replanner")
        p = out["prompt"]
        self.assertIn("You are a PLANNER", p)
        self.assertIn("do NOT execute", p)
        self.assertIn("APPENDING", p)
        self.assertIn("Don't repeat completed work", p)
        self.assertIn("Token budget", p)

    def test_malformed_checkbox_lines(self):
        write_state(self.nw)
        self.write_plan(MALFORMED_PLAN)
        out = self.hb()
        self.assertEqual(out["action"], "spawn_tasks")
        texts = [t["text"] for t in out["tasks"]]
        # good, missing-space, empty-box, star-bullet all unchecked tasks;
        # capital-X is checked; indented and plain bullets are not tasks.
        self.assertEqual(len(texts), 4)
        self.assertTrue(any("Good task one" in t for t in texts))
        self.assertTrue(any("Missing space" in t for t in texts))
        self.assertTrue(any("Empty box" in t for t in texts))
        self.assertTrue(any("Star bullet" in t for t in texts))
        self.assertFalse(any("Capital X" in t for t in texts))
        self.assertFalse(any("indented" in t for t in texts))

    # ---- outcome journal (A10) ------------------------------------------

    def test_task_prompt_outcome_journal(self):
        write_state(self.nw)
        self.write_plan(FRESH_PLAN)
        out = self.hb()
        self.assertEqual(out["action"], "spawn_tasks")
        for t in out["tasks"]:
            p = t["prompt"]
            self.assertIn("OUTCOME JOURNAL", p)
            self.assertIn(str(self.nw / "outcomes" / f"{PLAN_DATE}.jsonl"), p)
            self.assertIn(t["dispatch_id"], p)  # baked-in verbatim id
            self.assertIn('"quality_signal": "strong|adequate|weak"', p)
            self.assertIn("followup_candidate", p)
            self.assertIn('"status": "done|partial|blocked"', p)
            # existing behavior unchanged
            self.assertIn("- [ ]` to `- [x]", p)
            self.assertIn("overnight log", p)

    def test_task_prompt_status_contract(self):
        # Every executor prompt bakes in the bounded STATUS CONTRACT with the
        # task's own dispatch_id as TASK_ID (DACS REGISTRY discipline).
        write_state(self.nw)
        self.write_plan(FRESH_PLAN)
        out = self.hb()
        self.assertEqual(out["action"], "spawn_tasks")
        for t in out["tasks"]:
            p = t["prompt"]
            self.assertIn("STATUS CONTRACT", p)
            self.assertIn("STATUS: ok | partial | error", p)
            self.assertIn(f"TASK_ID: {t['dispatch_id']}", p)
            self.assertIn("NEEDS_ATTENTION:", p)
            self.assertIn("ARTIFACTS:", p)
            self.assertIn("FOLLOWUP:", p)
            # bound is stated so executors keep it compact
            self.assertIn("200 tokens", p)

    def test_replanner_prompt_wide_vs_deep_no_outcomes(self):
        write_state(self.nw)
        self.write_plan(EXHAUSTED_PLAN)
        out = self.hb()
        self.assertEqual(out["action"], "spawn_replanner")
        p = out["prompt"]
        self.assertIn("WIDE vs DEEP", p)
        self.assertIn(str(self.nw / "outcomes" / f"{PLAN_DATE}.jsonl"), p)
        self.assertIn("No outcome journal entries", p)
        self.assertIn("[deep: builds on task N]", p)
        self.assertIn("[wide]", p)
        # no strong followup -> no forced-deep clause
        self.assertNotIn("MUST either include at least one deep task", p)

    def test_replanner_prompt_inlines_outcomes_forces_deep(self):
        write_state(self.nw)
        self.write_plan(EXHAUSTED_PLAN)
        self.write_outcomes([
            {"task": "1. First task alpha", "dispatch_id": "d-aaaa1111",
             "status": "done", "attempted": "built the index",
             "outcome": "index exists with 40 rows",
             "quality_signal": "strong",
             "followup_candidate": "backfill the remaining 200 rows"},
            {"task": "2. Second task beta", "dispatch_id": "d-bbbb2222",
             "status": "partial", "attempted": "drafted the report",
             "outcome": "half a draft", "quality_signal": "weak",
             "followup_candidate": None},
        ])
        out = self.hb()
        self.assertEqual(out["action"], "spawn_replanner")
        p = out["prompt"]
        # journal entries inlined verbatim
        self.assertIn("index exists with 40 rows", p)
        self.assertIn("half a draft", p)
        # strong + followup -> forced consideration of a deep task
        self.assertIn("MUST either include at least one deep task", p)
        self.assertIn("backfill the remaining 200 rows", p)
        self.assertIn("Deep-vs-wide:", p)

    def test_replanner_outcomes_bad_lines_skipped(self):
        write_state(self.nw)
        self.write_plan(EXHAUSTED_PLAN)
        out_dir = self.nw / "outcomes"
        out_dir.mkdir(exist_ok=True)
        (out_dir / f"{PLAN_DATE}.jsonl").write_text(
            "not json at all\n"
            + json.dumps({"task": "1. First task alpha", "status": "done",
                          "outcome": "survivor entry",
                          "quality_signal": "adequate",
                          "followup_candidate": None}) + "\n")
        out = self.hb()
        self.assertEqual(out["action"], "spawn_replanner")
        self.assertIn("survivor entry", out["prompt"])

    def test_after_midnight_outcomes_path_uses_evening_date(self):
        write_state(self.nw)  # started_at 2026-07-01T21:00
        self.write_plan(FRESH_PLAN, date="2026-07-01")
        self.set_now(datetime(2026, 7, 2, 1, 15, tzinfo=TZ))
        out = self.hb()
        self.assertEqual(out["action"], "spawn_tasks")
        self.assertIn(str(self.nw / "outcomes" / "2026-07-01.jsonl"),
                      out["tasks"][0]["prompt"])

    # ---- heartbeat: journal / in-flight --------------------------------

    def test_task_in_flight_noop(self):
        write_state(self.nw)
        self.write_plan(FRESH_PLAN)
        out = self.hb()
        for t in out["tasks"]:
            self.ack(t["dispatch_id"], "spawned")
        out2 = self.hb()
        self.assertEqual(out2["action"], "noop")
        self.assertIn("in flight", out2["reason"])

    def test_issued_unspawned_blocks_within_grace(self):
        write_state(self.nw)
        self.write_plan(FRESH_PLAN)
        self.hb()  # issued, never acked spawned
        self.set_now(NIGHT + timedelta(minutes=5))
        out = self.hb()
        self.assertEqual(out["action"], "noop")

    def test_issued_unspawned_expires_after_grace(self):
        write_state(self.nw)
        self.write_plan(FRESH_PLAN)
        self.hb()  # issued, orchestrator crashed before spawning
        self.set_now(NIGHT + timedelta(minutes=20))
        out = self.hb()
        self.assertEqual(out["action"], "spawn_tasks")

    def test_checkbox_backstop_unblocks(self):
        # spawned + never acked completed, but the task checked its own box
        write_state(self.nw)
        self.write_plan(MID_GROUP_PLAN)
        out = self.hb()
        self.ack(out["tasks"][0]["dispatch_id"], "spawned")
        self.write_plan(GROUP1_DONE_PLAN)  # subagent flipped the checkbox
        out2 = self.hb()
        self.assertEqual(out2["action"], "spawn_tasks")
        self.assertIn("Group 2", out2["group"])

    def test_stale_journal_expiry(self):
        write_state(self.nw)
        self.write_plan(FRESH_PLAN)
        old = NIGHT - timedelta(hours=25)
        self.set_now(old)
        out = self.hb()
        self.ack(out["tasks"][0]["dispatch_id"], "spawned")
        self.set_now(NIGHT)
        out2 = self.hb()
        self.assertEqual(out2["action"], "spawn_tasks",
                         "25h-old spawned entry must not wedge the loop")

    def test_planner_in_flight_blocks_second_planner(self):
        write_state(self.nw)  # no plan file
        out = self.hb()
        self.assertEqual(out["action"], "spawn_planner")
        self.ack(out["dispatch_id"], "spawned")
        out2 = self.hb()
        self.assertEqual(out2["action"], "noop")
        self.assertIn("in flight", out2["reason"])

    def test_run_skill_nightwatch_blocks_heartbeat_planner(self):
        # the scheduled run_skill(nightwatch) planner must not be doubled
        write_state(self.nw)
        out = dispatch.run(["run_skill", "--skill", "nightwatch"])
        self.ack(out["dispatch_id"], "spawned")
        out2 = self.hb()
        self.assertEqual(out2["action"], "noop")

    # ---- heartbeat: failure/retry protocol ------------------------------

    def test_failed_once_respawns_with_context(self):
        write_state(self.nw)
        self.write_plan(MID_GROUP_PLAN)
        out = self.hb()
        rid = out["tasks"][0]["dispatch_id"]
        self.ack(rid, "spawned")
        self.ack(rid, "failed", note="qdrant timeout")
        out2 = self.hb()
        self.assertEqual(out2["action"], "spawn_tasks")
        t = out2["tasks"][0]
        self.assertTrue(t["retry"])
        self.assertIn("RETRY", t["prompt"])
        self.assertIn("qdrant timeout", t["prompt"])
        self.assertIn("FINAL automated attempt", t["prompt"])

    def test_failed_twice_surfaces_then_quarantines(self):
        write_state(self.nw)
        self.write_plan(MID_GROUP_PLAN)
        for attempt in range(2):
            out = self.hb()
            self.assertEqual(out["action"], "spawn_tasks")
            rid = out["tasks"][0]["dispatch_id"]
            self.ack(rid, "spawned")
            self.ack(rid, "failed", note=f"boom {attempt}")
        out = self.hb()
        self.assertEqual(out["action"], "surface_to_user")
        self.assertIn("failed twice", out["message"])
        self.assertIn("Second task beta", out["message"])
        self.ack(out["dispatch_id"], "completed")
        # quarantined task is skipped; loop proceeds to group 2
        out2 = self.hb()
        self.assertEqual(out2["action"], "spawn_tasks")
        self.assertIn("Group 2", out2["group"])
        # replanner prompt later carries the quarantine list
        self.write_plan(GROUP1_DONE_PLAN.replace(
            "- [x] 2. Second task beta", "- [ ] 2. Second task beta").replace(
            "- [ ] 3. Third task gamma", "- [x] 3. Third task gamma"))
        out3 = self.hb()
        self.assertEqual(out3["action"], "spawn_replanner")
        self.assertIn("quarantined", out3["prompt"])
        self.assertIn("Second task beta", out3["prompt"])

    def test_replanner_double_fail_surfaces(self):
        write_state(self.nw)
        self.write_plan(EXHAUSTED_PLAN)
        for attempt in range(2):
            out = self.hb()
            self.assertEqual(out["action"], "spawn_replanner")
            self.ack(out["dispatch_id"], "spawned")
            self.ack(out["dispatch_id"], "failed", note=f"crash {attempt}")
        out = self.hb()
        self.assertEqual(out["action"], "surface_to_user")
        self.assertIn("re-planner failed", out["message"])
        self.ack(out["dispatch_id"], "completed")
        # and it doesn't re-surface every heartbeat
        out2 = self.hb()
        self.assertEqual(out2["action"], "noop")

    def test_replanner_loop_guard(self):
        # replanner "completes" twice without producing tasks -> halt+surface
        write_state(self.nw)
        self.write_plan(EXHAUSTED_PLAN)
        for _ in range(2):
            out = self.hb()
            self.assertEqual(out["action"], "spawn_replanner")
            self.ack(out["dispatch_id"], "spawned")
            self.ack(out["dispatch_id"], "completed")
        out = self.hb()
        self.assertEqual(out["action"], "surface_to_user")
        self.assertIn("completed twice", out["message"])

    # ---- plan date resolution -------------------------------------------

    def test_after_midnight_reads_yesterdays_plan(self):
        write_state(self.nw)  # started_at 2026-07-01T21:00
        self.write_plan(FRESH_PLAN, date="2026-07-01")
        self.set_now(datetime(2026, 7, 2, 1, 15, tzinfo=TZ))
        out = self.hb()
        self.assertEqual(out["action"], "spawn_tasks")
        self.assertIn("2026-07-01-plan.md", out["plan"])

    # ---- re-plan group appended (real-world shape) -----------------------

    def test_appended_replan_group_is_picked_up(self):
        write_state(self.nw)
        plan = EXHAUSTED_PLAN + (
            "\n## Group 4 (APPENDED 21:50 ET -- re-plan after exhaustion)\n"
            "\n**Re-plan honesty note.** Constraint bullets follow:\n"
            "- **GOOGLE IS DOWN** -- not a task, just a note.\n"
            "\n- [ ] 7. Appended cleanup task | operator | S | anti-rot\n"
        )
        self.write_plan(plan)
        out = self.hb()
        self.assertEqual(out["action"], "spawn_tasks")
        self.assertIn("Group 4", out["group"])
        self.assertEqual(len(out["tasks"]), 1)
        self.assertIn("Appended cleanup task", out["tasks"][0]["text"])

    # NOTE: the private repo also exercises two real overnight plan files as
    # parser fixtures. Those contain personal content and are intentionally not
    # ported; the synthetic inline plans above cover the same parser paths
    # (multi-group parse, appended-group handling, all-checked -> replan,
    # partial -> spawn_tasks).

    # ---- nightwatch_start / nightwatch_stop ------------------------------

    def test_start_hours(self):
        out = dispatch.run(["nightwatch_start", "--hours", "4"])
        self.assertEqual(out["action"], "spawn_planner")
        state = json.loads((self.nw / ".nightwatch-state.json").read_text())
        self.assertTrue(state["active"])
        self.assertEqual(state["trigger"], "manual")
        stop = datetime.fromisoformat(state["stop_at"])
        self.assertEqual(stop, NIGHT + timedelta(hours=4))
        self.assertEqual(datetime.fromisoformat(state["started_at"]), NIGHT)
        self.assertIn("2026-07-01-plan.md", out["prompt"])

    def test_start_until_rolls_to_tomorrow(self):
        out = dispatch.run(["nightwatch_start", "--until", "03:30"])
        state = json.loads((self.nw / ".nightwatch-state.json").read_text())
        stop = datetime.fromisoformat(state["stop_at"])
        self.assertEqual(stop, datetime(2026, 7, 2, 3, 30, tzinfo=TZ))
        self.assertEqual(out["action"], "spawn_planner")

    def test_start_without_args_errors(self):
        # stdin is not a tty under test runners; feed empty stdin JSON path
        out = dispatch.handle_nightwatch_start(None, None)
        self.assertEqual(out["action"], "report_error")

    def test_stop_sets_inactive(self):
        write_state(self.nw)
        out = dispatch.run(["nightwatch_stop"])
        self.assertEqual(out["action"], "noop")
        state = json.loads((self.nw / ".nightwatch-state.json").read_text())
        self.assertFalse(state["active"])
        self.assertIn("finishes its current task", out["reason"])
        # heartbeat after stop is a noop
        self.write_plan(FRESH_PLAN)
        self.assertEqual(self.hb()["action"], "noop")

    # ---- ack -------------------------------------------------------------

    def test_ack_unknown_id(self):
        out = self.ack("d-deadbeef", "completed")
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
