"""Run every scenario through the pipeline and grade it.

    coach evals --scripted            # the harness with the scripted rules (no API key, runs in CI)
    coach evals                       # the real agents (needs ANTHROPIC_API_KEY)
    coach evals --repeats 3           # also checks stability: the same week gets the same level each time
    coach evals --langsmith           # and logs the results to LangSmith (needs LANGSMITH_API_KEY)

Exit code 1 if any check fails, so CI can gate prompt and skill changes on it.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from coach.flow import Context
from coach.profile import load_athlete, load_library
from coach.runner import run_plain

from .evaluators import evaluate
from .scenarios import SCENARIOS

OUT = Path("out")


def _llm(scripted: bool):
    if scripted:
        from .scripted import scripted_llm

        return scripted_llm()
    from coach.llm import AnthropicLLM

    return AnthropicLLM()


def run_one(name: str, scripted: bool = True) -> dict:
    s = next(x for x in SCENARIOS if x.name == name)
    ctx = Context(llm=_llm(scripted), athlete=load_athlete(), library=load_library(), snapshot_json=s.snapshot())
    return run_plain(ctx)


def main(scripted: bool = False, repeats: int = 1, langsmith: bool = False) -> int:
    rows, failed = [], 0
    judge_on = not scripted and bool(os.environ.get("ANTHROPIC_API_KEY"))
    for s in SCENARIOS:
        levels = []
        for i in range(repeats):
            ctx = Context(llm=_llm(scripted), athlete=load_athlete(), library=load_library(), snapshot_json=s.snapshot())
            state = run_plain(ctx)
            checks = evaluate(state, s.expect)
            if judge_on and i == 0 and state["decision"].recommendation != "none":
                from .judge import judge

                g = judge(state)
                checks["judge"] = (g.passed, g.notes)
            levels.append(state["decision"].change_level)
            ok = all(v[0] for v in checks.values())
            failed += 0 if ok else 1
            rows.append({"scenario": s.name, "run": i + 1, "ok": ok, "level": state["decision"].change_level, "recommendation": state["decision"].recommendation, "path": " → ".join(state.get("path", [])), "checks": {k: {"pass": v[0], "detail": v[1]} for k, v in checks.items()}})
        if repeats > 1 and len(set(levels)) > 1:
            failed += 1
            rows.append({"scenario": s.name, "run": "stability", "ok": False, "level": levels, "checks": {"stability": {"pass": False, "detail": f"levels {levels}"}}})

    width = max(len(s.name) for s in SCENARIOS)
    for r in rows:
        bad = "; ".join(f"{k}: {v['detail']}" for k, v in r["checks"].items() if not v["pass"])
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {r['scenario']:<{width}}  run {r['run']}  level {r['level']}  {r.get('recommendation', '')}  {bad}")
    print(f"\n{len(rows) - failed}/{len(rows)} passed ({'scripted rules' if scripted else 'model'})")
    OUT.mkdir(exist_ok=True)
    (OUT / f"evals-{date.today().isoformat()}.json").write_text(json.dumps(rows, indent=2, default=str))
    if langsmith:
        _to_langsmith(rows, scripted)
    return 1 if failed else 0


def _to_langsmith(rows: list[dict], scripted: bool) -> None:
    """Log each scenario result to LangSmith as feedback on a run in the 'workout-coach-evals' project."""
    try:
        from langsmith import Client  # type: ignore
    except ImportError:
        print("langsmith isn't installed; skipped.")
        return
    client = Client()
    project = os.environ.get("LANGSMITH_PROJECT", "workout-coach") + "-evals"
    for r in rows:
        run = client.create_run(name=f"eval:{r['scenario']}", run_type="chain", inputs={"scenario": r["scenario"], "scripted": scripted}, outputs={"level": r["level"], "ok": r["ok"]}, project_name=project)
        run_id = getattr(run, "id", None)
        if run_id:
            for k, v in r["checks"].items():
                client.create_feedback(run_id, key=k, score=1 if v["pass"] else 0, comment=v["detail"] or None)
    print(f"Logged {len(rows)} results to LangSmith project {project}.")


if __name__ == "__main__":
    import sys

    raise SystemExit(main(scripted="--scripted" in sys.argv))
