#!/usr/bin/env python3
"""GEPA metric: score a sandboxed skill run with the skill-evals suite.

Score = pass fraction over the skill's full suite (PASS / (PASS+FAIL); SKIPs
excluded -- report-target checks always SKIP headless). Side information =
the failing checks' names + detail messages, which is GEPA's Actionable Side
Information: the reflection model reads these to decide what in the skill
text to change.

Hard-fail conditions score 0.0 with the reason as side info:
  * runner produced no artifact
  * runner timed out / errored

Usage:
  metric.py --result <sandbox>/result.json          # score a runner result
  metric.py --artifact <path> [--skill morning-brief]
Output: JSON {score, passed, failed, skipped, side_info: [..], artifact}.
Never writes eval history (this is optimization traffic, not the daily
regression baseline).
"""

import argparse
import importlib.machinery
import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
import os
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
EDWIN_HOME = Path(os.environ.get("EDWIN_HOME", TOOL_DIR.parent.parent))
SKILL_EVALS = EDWIN_HOME / "tools" / "skill-evals" / "skill-evals"


def load_skill_evals():
    loader = importlib.machinery.SourceFileLoader("skill_evals", str(SKILL_EVALS))
    spec = importlib.util.spec_from_loader("skill_evals", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def score_artifact(skill, artifact):
    se = load_skill_evals()
    suite = se.load_suite(skill)
    if suite is None:
        return {"score": 0.0, "passed": 0, "failed": 0, "skipped": 0,
                "side_info": [f"HARD FAIL: no skill-evals suite for {skill}"], "artifact": artifact}
    buf = io.StringIO()
    with redirect_stdout(buf):
        rows = se.run_suite(skill, suite, artifact_override=artifact, log=lambda *a: None)
    passed = sum(1 for r in rows if r["status"] == "PASS")
    failed = sum(1 for r in rows if r["status"] == "FAIL")
    skipped = sum(1 for r in rows if r["status"] == "SKIP")
    graded = passed + failed
    side = [f"{r['name']}: {r['detail']}" for r in rows if r["status"] == "FAIL"]
    return {"score": round(passed / graded, 4) if graded else 0.0,
            "passed": passed, "failed": failed, "skipped": skipped,
            "side_info": side, "artifact": artifact}


def hard_fail(reason, artifact=None):
    return {"score": 0.0, "passed": 0, "failed": 0, "skipped": 0,
            "side_info": [f"HARD FAIL: {reason}"], "artifact": artifact}


def score_result(skill, result_path):
    result = json.loads(Path(result_path).read_text())
    skill = result.get("skill", skill)
    if result.get("error"):
        # timeout or nonzero exit; an artifact may still exist -- a run that
        # died AFTER publishing gets partial credit only if the artifact is real
        if not result.get("artifact"):
            return hard_fail(f"runner error, no artifact: {result['error']}")
        m = score_artifact(skill, result["artifact"])
        m["side_info"].append(f"runner error (artifact was still produced): {result['error']}")
        return m
    if not result.get("artifact"):
        return hard_fail("no artifact produced at the expected briefing-book path "
                         "(skill must write 'Morning Brief -- YYYY-MM-DD.md')")
    return score_artifact(skill, result["artifact"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", default="morning-brief")
    ap.add_argument("--result", help="runner result.json")
    ap.add_argument("--artifact", help="score an artifact directly")
    args = ap.parse_args()
    if not args.result and not args.artifact:
        ap.error("need --result or --artifact")
    m = score_result(args.skill, args.result) if args.result else score_artifact(args.skill, args.artifact)
    print(json.dumps(m, indent=2))
    sys.exit(0 if m["score"] > 0 else 1)


if __name__ == "__main__":
    main()
