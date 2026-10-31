"""One weekly run, as a service: what the Vercel function (api/run.py) calls.

Same pipeline as `coach run`: read the history from the app, run the agents, write the report and,
unless publishing is turned off, save it to the app. Every failure still ends in an honest report
(the pipeline's failsafe); only missing settings stop it before it starts.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

from .flow import Context
from .profile import load_athlete, load_library
from .runner import run

REQUIRED = ("WORKOUT_AGENT_URL", "WORKOUT_AGENT_KEY", "ANTHROPIC_API_KEY")


def missing_settings(env: Optional[dict] = None) -> list[str]:
    env = os.environ if env is None else env
    return [k for k in REQUIRED if not (env.get(k) or "").strip()]


def tracing_defaults(env: Optional[dict] = None) -> None:
    """With a LangSmith key set, trace every run unless tracing is explicitly turned off."""
    env = os.environ if env is None else env
    if (env.get("LANGSMITH_API_KEY") or "").strip():
        env.setdefault("LANGSMITH_TRACING", "true")
        env.setdefault("LANGSMITH_PROJECT", "workout-coach")


def publishing(env: Optional[dict] = None) -> bool:
    """On by default: on Vercel the app is where you read reports. COACH_PUBLISH=false keeps them out."""
    env = os.environ if env is None else env
    return (env.get("COACH_PUBLISH") or "true").strip().lower() != "false"


def run_weekly(
    as_of: Optional[str] = None,
    *,
    client: Any = None,
    llm: Any = None,
    publish: Optional[bool] = None,
    use_langgraph: bool = True,
    on_state: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Run the coach once. Returns a short summary (what the function answers with)."""
    if client is None:
        from .client import AppClient

        client = AppClient()
    if llm is None:
        from .llm import AnthropicLLM

        llm = AnthropicLLM()
    do_publish = publishing() if publish is None else publish
    ctx = Context(
        llm=llm,
        athlete=load_athlete(),
        library=load_library(),
        as_of=as_of,
        fetch=lambda a, months: client.history(a, months),
        publish=(lambda payload: client.save_report(payload)) if do_publish else None,
    )
    state = run(ctx, use_langgraph=use_langgraph)
    if on_state:
        on_state(state)
    d = state["decision"]
    return {
        "as_of": state["payload"]["as_of"],
        "recommendation": d.recommendation,
        "change_level": d.change_level,
        "summary": d.summary,
        "changes": len(d.changes),
        "published": bool(state.get("published")),
        "saved": state.get("published"),
        "failed": bool(state.get("failed")),
        "error": state.get("error"),
    }
