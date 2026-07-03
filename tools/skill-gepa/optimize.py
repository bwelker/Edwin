#!/usr/bin/env python3
"""GEPA optimization of a SKILL.md against frozen skill-evals fixtures.

Run with the tool venv: tools/skill-gepa/venv/bin/python optimize.py

Wiring (arXiv 2507.19457, gepa-ai/gepa):
  * candidate     = {"skill_body": <full SKILL.md text>}
  * task executor = run_skill_on_fixtures.py (headless claude, Haiku,
                    fixture-sandboxed -- see that file's guardrails)
  * metric        = metric.py (skill-evals suite pass fraction; failing check
                    names + messages are the Actionable Side Information)
  * trainset      = one DataInst per frozen fixture day. More days accumulate
                    via `skill-evals fixtures freeze <skill>` (weekly nightwatch
                    task); GEPA is usable from ~3 examples, one day is
                    proof-of-life thin.
  * reflection LM = claude-sonnet-5 via the Anthropic API (stdlib HTTP; key
                    from ~/.edwin/credentials/anthropic/env)

Budgets: --max-metric-calls (each call = one full sandboxed skill run on
Haiku, minutes each) and --max-cost-usd summed from the runner's reported
total_cost_usd (reflection cost is NOT included in the guard; it is small
relative to rollouts). When the cost guard trips, optimization stops via
stop_callbacks and the best candidate so far is still reported.

Nothing here ever touches skills/<skill>/SKILL.md. Best candidate lands in
candidates/<stamp>-best.md with scores + a unified diff vs the seed.
"""

import argparse
import difflib
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
import os
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
EDWIN_HOME = Path(os.environ.get("EDWIN_HOME", TOOL_DIR.parent.parent))
FIXTURES = EDWIN_HOME / "tools" / "skill-evals" / "fixtures"
CREDS_FILE = Path.home() / ".edwin/credentials/anthropic/env"

REFLECTION_MODEL = "claude-sonnet-5"


def load_api_key():
    for line in CREDS_FILE.read_text().strip().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1]
    raise SystemExit(f"no ANTHROPIC_API_KEY in {CREDS_FILE}")


def make_reflection_lm(api_key, log):
    def lm(prompt):
        if isinstance(prompt, str):
            messages = [{"role": "user", "content": prompt}]
        else:
            messages = [m for m in prompt if m.get("role") != "system"]
        system = None
        if not isinstance(prompt, str):
            sys_msgs = [m["content"] for m in prompt if m.get("role") == "system"]
            system = "\n".join(sys_msgs) if sys_msgs else None
        body = {"model": REFLECTION_MODEL, "max_tokens": 16000, "messages": messages}
        if system:
            body["system"] = system
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode(),
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    data = json.loads(resp.read())
                text = "".join(b.get("text", "") for b in data.get("content", []))
                log(f"  [reflection] {REFLECTION_MODEL}: {len(text)} chars out")
                return text
            except Exception as e:
                if attempt == 2:
                    raise
                log(f"  [reflection] retry after {e}")
                time.sleep(10 * (attempt + 1))
    return lm


class SkillGepaAdapter:
    """GEPAAdapter over the fixture-sandboxed runner + skill-evals metric."""

    def __init__(self, skill, run_root, model, max_turns, timeout, log, cost_ledger):
        self.skill = skill
        self.run_root = run_root
        self.model = model
        self.max_turns = max_turns
        self.timeout = timeout
        self.log = log
        self.cost_ledger = cost_ledger  # dict: {"spent": float, "calls": int}
        self.propose_new_texts = None   # use GEPA's default instruction proposer

    def _rollout(self, candidate_text, fixture_date):
        self.cost_ledger["calls"] += 1
        n = self.cost_ledger["calls"]
        sandbox = self.run_root / f"call-{n:03d}-{fixture_date}"
        cand_file = sandbox.parent / f"call-{n:03d}-candidate.md"
        sandbox.parent.mkdir(parents=True, exist_ok=True)
        cand_file.write_text(candidate_text)

        t0 = time.time()
        proc = subprocess.run(
            ["python3", str(TOOL_DIR / "run_skill_on_fixtures.py"),
             "--skill", self.skill, "--fixture-date", fixture_date,
             "--candidate", str(cand_file), "--sandbox-dir", str(sandbox),
             "--model", self.model, "--max-turns", str(self.max_turns),
             "--timeout", str(self.timeout)],
            capture_output=True, text=True, timeout=self.timeout + 120)
        result_file = sandbox / "result.json"
        if result_file.exists():
            result = json.loads(result_file.read_text())
        else:
            result = {"error": f"runner crashed: {proc.stderr[-500:]}", "artifact": None}

        mproc = subprocess.run(
            ["python3", str(TOOL_DIR / "metric.py"), "--skill", self.skill,
             "--result", str(result_file)] if result_file.exists() else ["true"],
            capture_output=True, text=True)
        try:
            metric = json.loads(mproc.stdout)
        except json.JSONDecodeError:
            metric = {"score": 0.0, "side_info": [f"metric crashed: {mproc.stderr[-500:]}"]}

        cost = result.get("cost_usd") or 0.0
        self.cost_ledger["spent"] += cost
        self.log(f"  [rollout {n}] {fixture_date} score={metric['score']} "
                 f"cost=${cost:.2f} (total ${self.cost_ledger['spent']:.2f}) "
                 f"dur={result.get('duration_s')}s turns={result.get('num_turns')}")
        return result, metric

    def evaluate(self, batch, candidate, capture_traces=False):
        from gepa.core.adapter import EvaluationBatch
        outputs, scores, trajectories = [], [], []
        for ex in batch:
            try:
                result, metric = self._rollout(candidate["skill_body"], ex["fixture_date"])
            except Exception as e:  # never raise per-example
                result, metric = {"artifact": None}, {"score": 0.0,
                                                      "side_info": [f"rollout exception: {e}"]}
            artifact_text = ""
            if result.get("artifact") and Path(result["artifact"]).exists():
                artifact_text = Path(result["artifact"]).read_text()
            outputs.append({"result": result, "metric": metric,
                            "artifact_text": artifact_text})
            scores.append(metric["score"])
            trajectories.append({"fixture_date": ex["fixture_date"],
                                 "metric": metric,
                                 "artifact_excerpt": artifact_text[:6000],
                                 "report_text": (result.get("report_text") or "")[-2000:]})
        return EvaluationBatch(outputs=outputs, scores=scores,
                               trajectories=trajectories if capture_traces else None)

    def make_reflective_dataset(self, candidate, eval_batch, components_to_update):
        items = []
        for traj, score in zip(eval_batch.trajectories, eval_batch.scores):
            m = traj["metric"]
            feedback = (f"Score {score} (pass fraction of {m.get('passed', 0)+m.get('failed', 0)} "
                        f"deterministic output checks). ")
            if m.get("side_info"):
                feedback += "FAILING CHECKS (fix the skill instructions so these pass):\n- " \
                            + "\n- ".join(m["side_info"])
            else:
                feedback += "All checks passed. Tighten the instructions only where they are " \
                            "ambiguous, redundant, or waste the executing agent's turns."
            items.append({
                "Inputs": {"task": f"Execute the {self.skill} skill against the frozen "
                                   f"data snapshot for {traj['fixture_date']} and produce "
                                   f"the brief artifact.",
                           "fixture_date": traj["fixture_date"]},
                "Generated Outputs": {"artifact_excerpt": traj["artifact_excerpt"],
                                      "completion_report": traj["report_text"]},
                "Feedback": feedback,
            })
        return {"skill_body": items}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", default="morning-brief")
    ap.add_argument("--max-metric-calls", type=int, default=25)
    ap.add_argument("--max-cost-usd", type=float, default=15.0)
    ap.add_argument("--model", default="claude-haiku-4-5-20251001")
    ap.add_argument("--max-turns", type=int, default=100)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--reflection-minibatch-size", type=int, default=1)
    args = ap.parse_args()

    import gepa

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_root = TOOL_DIR / "runs" / f"gepa-{stamp}"
    run_root.mkdir(parents=True)
    log_file = open(run_root / "optimize.log", "a")

    def log(msg):
        line = f"{datetime.now().strftime('%H:%M:%S')} {msg}"
        print(line, flush=True)
        log_file.write(line + "\n")
        log_file.flush()

    seed_file = EDWIN_HOME / "skills" / args.skill / "SKILL.md"
    seed_text = seed_file.read_text()
    seed_candidate = {"skill_body": seed_text}

    fixture_days = sorted(d.name for d in (FIXTURES / args.skill).iterdir() if d.is_dir())
    trainset = [{"fixture_date": d} for d in fixture_days]
    log(f"skill={args.skill} trainset={fixture_days} "
        f"budget={args.max_metric_calls} metric calls / ${args.max_cost_usd}")
    if len(trainset) < 3:
        log(f"NOTE: only {len(trainset)} fixture day(s) -- GEPA wants >=3; "
            "proof-of-life mode. Freeze more days weekly.")

    anthropic_ak = load_api_key()
    cost_ledger = {"spent": 0.0, "calls": 0}
    adapter = SkillGepaAdapter(args.skill, run_root, args.model, args.max_turns,
                               args.timeout, log, cost_ledger)

    def cost_stopper(gepa_state=None):
        return cost_ledger["spent"] >= args.max_cost_usd

    result = gepa.optimize(
        seed_candidate=seed_candidate,
        trainset=trainset,
        valset=trainset,  # one frozen day: train == val (documented limitation)
        adapter=adapter,
        reflection_lm=make_reflection_lm(anthropic_ak, log),
        reflection_minibatch_size=args.reflection_minibatch_size,
        max_metric_calls=args.max_metric_calls,
        stop_callbacks=[cost_stopper],
        run_dir=str(run_root),
        track_best_outputs=True,
        display_progress_bar=False,
        raise_on_exception=False,
        seed=0,
    )

    best = result.best_candidate["skill_body"]
    best_score = result.val_aggregate_scores[result.best_idx]
    seed_score = result.val_aggregate_scores[0]
    diff = "".join(difflib.unified_diff(
        seed_text.splitlines(keepends=True), best.splitlines(keepends=True),
        fromfile=f"seed ({args.skill}/SKILL.md)", tofile="gepa-best"))

    out_base = TOOL_DIR / "candidates" / f"{stamp}-{args.skill}"
    (TOOL_DIR / "candidates").mkdir(exist_ok=True)
    Path(f"{out_base}-best.md").write_text(best)
    Path(f"{out_base}-diff.patch").write_text(diff or "(best candidate == seed)\n")
    Path(f"{out_base}-scores.json").write_text(json.dumps({
        "skill": args.skill, "stamp": stamp,
        "seed_score": seed_score, "best_score": best_score,
        "best_idx": result.best_idx,
        "num_candidates": len(result.candidates),
        "val_aggregate_scores": result.val_aggregate_scores,
        "metric_calls": cost_ledger["calls"],
        "rollout_cost_usd": round(cost_ledger["spent"], 2),
        "trainset_days": fixture_days,
        "model": args.model, "reflection_model": REFLECTION_MODEL,
    }, indent=2))

    log(f"DONE seed={seed_score} best={best_score} candidates={len(result.candidates)} "
        f"calls={cost_ledger['calls']} cost=${cost_ledger['spent']:.2f}")
    log(f"best candidate: {out_base}-best.md  (diff: {out_base}-diff.patch)")
    log("Adoption is the operator/orchestrator's call -- the live SKILL.md was not touched.")


if __name__ == "__main__":
    main()
