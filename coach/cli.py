"""coach: run the weekly review, check access, replay past weeks, run the evals.

    coach run                       # this week, dry run: writes out/report-<date>.md, saves nothing
    coach run --publish             # and saves the report to the app
    coach run --as-of 2026-11-06 --snapshot evals/fixtures/all_progressing.json --scripted
    coach history --format md       # what the agent can see, as the app renders it
    coach backtest --from 2026-11-06 --to 2027-01-29
    coach evals [--scripted]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .flow import Context
from .profile import load_athlete, load_library

OUT = Path("out")


def _llm(scripted: bool):
    if scripted:
        from evals.scripted import scripted_llm  # type: ignore

        return scripted_llm()
    from .llm import AnthropicLLM

    return AnthropicLLM()


def cmd_run(a: argparse.Namespace) -> int:
    from .client import AppClient
    from .runner import run

    snapshot = json.loads(Path(a.snapshot).read_text()) if a.snapshot else None
    client = None if snapshot is not None else AppClient()
    publish = a.publish or os.environ.get("COACH_PUBLISH", "").lower() == "true"
    ctx = Context(
        llm=_llm(a.scripted),
        athlete=load_athlete(),
        library=load_library(),
        as_of=a.as_of,
        months=a.months,
        fetch=(lambda as_of, months: client.history(as_of, months)) if client else None,
        publish=(lambda payload: (client or AppClient()).save_report(payload)) if publish else None,
        snapshot_json=snapshot,
    )
    state = run(ctx, use_langgraph=a.langgraph)
    OUT.mkdir(exist_ok=True)
    as_of = state["payload"]["as_of"] or "unknown"
    (OUT / f"report-{as_of}.md").write_text(state["report_md"])
    (OUT / f"decision-{as_of}.json").write_text(json.dumps(state["payload"]["decision"], indent=2))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(state["report_md"] + "\n")
    d = state["decision"]
    print(f"{d.recommendation} (level {d.change_level}): {d.summary}")
    print(f"Report: {OUT / f'report-{as_of}.md'}" + (f" · saved: {state.get('published')}" if state.get("published") else " · dry run, not saved"))
    return 1 if state.get("failed") else 0


def cmd_history(a: argparse.Namespace) -> int:
    from .client import AppClient

    c = AppClient()
    print(c.history_markdown(a.as_of, a.months) if a.format == "md" else json.dumps(c.history(a.as_of, a.months), indent=2))
    return 0


def cmd_backtest(a: argparse.Namespace) -> int:
    from evals.backtest import main as backtest  # type: ignore

    return backtest(a.start, a.end, scripted=a.scripted, months=a.months)


def cmd_evals(a: argparse.Namespace) -> int:
    from evals.run_evals import main as evals  # type: ignore

    return evals(scripted=a.scripted, repeats=a.repeats, langsmith=a.langsmith)


def main(argv: list[str] | None = None) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so `evals` imports from the repo
    p = argparse.ArgumentParser(prog="coach", description="Weekly workout review: reads your workout history, recommends a change or no change.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="review a week and write the report")
    r.add_argument("--as-of", help="YYYY-MM-DD (default: today in your time zone)")
    r.add_argument("--months", type=int, default=6)
    r.add_argument("--snapshot", help="read the snapshot from a file instead of the app")
    r.add_argument("--publish", action="store_true", help="save the report to the app (or set COACH_PUBLISH=true)")
    r.add_argument("--scripted", action="store_true", help="use the scripted model (no API key; for trying the pipeline)")
    r.add_argument("--langgraph", action="store_true", help="run through LangGraph (traces each step in LangSmith) instead of walking the same steps directly")
    r.set_defaults(fn=cmd_run)

    h = sub.add_parser("history", help="print what the agent can see")
    h.add_argument("--as-of")
    h.add_argument("--months", type=int, default=6)
    h.add_argument("--format", choices=["md", "json"], default="md")
    h.set_defaults(fn=cmd_history)

    b = sub.add_parser("backtest", help="replay past Fridays against the simple rule")
    b.add_argument("--from", dest="start", required=True)
    b.add_argument("--to", dest="end", required=True)
    b.add_argument("--months", type=int, default=6)
    b.add_argument("--scripted", action="store_true")
    b.set_defaults(fn=cmd_backtest)

    e = sub.add_parser("evals", help="run the scenario evals")
    e.add_argument("--scripted", action="store_true", help="check the harness with the scripted model")
    e.add_argument("--repeats", type=int, default=1, help="run each scenario N times (stability)")
    e.add_argument("--langsmith", action="store_true", help="also log the run to LangSmith")
    e.set_defaults(fn=cmd_evals)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
