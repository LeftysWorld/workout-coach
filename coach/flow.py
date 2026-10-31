"""The pipeline, defined once.

    load → check → facts → gate ─(too little data)──────────────────────────────┐
                              └→ analyst → planner → governor ─(all broke rules, │
                                              ▲         tries left)→ planner     │
                                              │      └→ score → critic          │
                                              └──(revise, once)──┘    │         │
                                                                   finalize ←───┘
                                                                      → render → publish → END
    Any error, anywhere → failsafe → render → publish: an honest "no recommendation this week".

NODES maps a name to a function (state, ctx) → partial state. ROUTES maps a name to the next name, or to
a function of the state. coach/runner.py walks this; coach/graph.py builds the same thing in LangGraph.
"""

from __future__ import annotations

import yaml

import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import metrics, numbers
from .agents import run_analyst, run_critic, run_planner
from .decision import TYPE_LEVEL, Assessment, CriticVerdict, Decision, Option, Options
from .governor import check as governor_check
from .llm import LLM
from .profile import Athlete, Library, apply_app_rules
from .score import REWARD_VERSION, option_score
from .snapshot import Snapshot, parse_snapshot

END = "__end__"
MAX_PLANNER_TRIES = 3  # the first proposal and two fixes
MAX_CRITIC_REVISIONS = 1


@dataclass
class Context:
    llm: LLM
    athlete: Athlete
    library: Library
    as_of: Optional[str] = None
    months: int = 6
    fetch: Optional[Callable[[Optional[str], int], dict]] = None  # (as_of, months) → snapshot JSON
    publish: Optional[Callable[[dict], dict]] = None  # report payload → response; None = dry run
    snapshot_json: Optional[dict] = None
    notes: list[str] = field(default_factory=list)
    rules_update: str = ""  # YAML of the rule sections changed in the app's Settings, for the prompts


State = dict[str, Any]


# ---------- Nodes ----------


def load(state: State, ctx: Context) -> State:
    raw = ctx.snapshot_json if ctx.snapshot_json is not None else ctx.fetch(ctx.as_of, ctx.months)  # type: ignore[misc]
    snap = parse_snapshot(raw)
    # Your rules from the app's Settings → Training win over athlete.yaml, for the rules check and the agents.
    rules = raw.get("training_rules") if isinstance(raw, dict) else None
    ctx.athlete, changed = apply_app_rules(ctx.athlete, rules, snap.meta.units)
    if changed:
        ctx.rules_update = yaml.safe_dump(changed, sort_keys=False, allow_unicode=True)
        ctx.notes.append("Using your training rules from the app's Settings (" + ", ".join(k.replace("_", " ") for k in changed) + ").")
    return {"snapshot": snap}


def check(state: State, ctx: Context) -> State:
    metrics.check_contract(state["snapshot"])
    return {}


def facts(state: State, ctx: Context) -> State:
    return {"facts": metrics.build_facts(state["snapshot"], ctx.athlete, ctx.library)}


def gate(state: State, ctx: Context) -> State:
    ok, why = metrics.enough_data(state["snapshot"])
    return {} if ok else {"skip_reason": why}


def analyst(state: State, ctx: Context) -> State:
    return {"assessment": run_analyst(ctx.llm, state["facts"], ctx.rules_update)}


def planner(state: State, ctx: Context) -> State:
    opts = run_planner(
        ctx.llm,
        state["facts"],
        state["assessment"],
        ctx.athlete,
        ctx.library,
        feedback=state.get("violations_text"),
        critic_note=state.get("critic_note"),
        rules_update=ctx.rules_update,
    )
    if not any(o.id == "hold" for o in opts.options):
        opts.options.append(Option(id="hold", label="Hold: no change", change_level=0, changes=[], rationale=["Added by the pipeline: a hold is always an option."]))
    return {"options": opts, "planner_tries": state.get("planner_tries", 0) + 1, "critic_note": None}


def governor(state: State, ctx: Context) -> State:
    s: Snapshot = state["snapshot"]
    block = state["facts"]["block"]
    passing: list[Option] = []
    rejected: dict[str, list[str]] = {}
    for o in state["options"].options:
        v = governor_check(o, s, ctx.athlete, ctx.library, block)
        if v:
            rejected[o.id] = [str(x) for x in v]
        else:
            passing.append(o)
    text = [f"{oid}: {msg}" for oid, msgs in rejected.items() for msg in msgs]
    return {"passing": passing, "rejected": {**state.get("rejected", {}), **{f"try{state.get('planner_tries', 1)}:{k}": v for k, v in rejected.items()}}, "violations_text": text}


def score(state: State, ctx: Context) -> State:
    return {"scores": {o.id: option_score(o, state["facts"], ctx.athlete) for o in state["passing"]}}


def critic(state: State, ctx: Context) -> State:
    can_revise = state.get("critic_rounds", 0) < MAX_CRITIC_REVISIONS
    verdict = run_critic(ctx.llm, state["facts"], state["assessment"], state["passing"], state["scores"], can_revise, ctx.rules_update)
    if verdict.verdict == "revise" and not can_revise:
        verdict = verdict.model_copy(update={"verdict": "accept"})
    if verdict.chosen_option_id not in {o.id for o in state["passing"]}:
        verdict = verdict.model_copy(update={"chosen_option_id": "hold", "verdict": "accept", "reasons": verdict.reasons + ["The critic picked an option that wasn't on the list; holding instead."]})
    out: State = {"verdict": verdict, "critic_rounds": state.get("critic_rounds", 0) + (1 if verdict.verdict == "revise" else 0)}
    if verdict.verdict == "revise":
        out["critic_note"] = verdict.revise_instructions or "; ".join(verdict.reasons)
        out["violations_text"] = None
    return out


def finalize(state: State, ctx: Context) -> State:
    s: Snapshot = state["snapshot"]
    block = state.get("facts", {}).get("block")
    if state.get("skip_reason"):
        return {"decision": Decision(recommendation="none", change_level=0, summary=f"No recommendation this week: {state['skip_reason']}", block=_block(block))}
    verdict: CriticVerdict = state["verdict"]
    option = next(o for o in state["passing"] if o.id == verdict.chosen_option_id)
    drop = {x.strip().lower() for x in verdict.drop_exercises} if verdict.verdict == "downgrade" else set()
    changes = [c for c in option.changes if c.exercise.strip().lower() not in drop]
    level = 0
    if changes:
        level = option.change_level if option.change_level >= 5 and any(c.type in {"deload", "swap", "add", "remove", "program"} for c in changes) else max(TYPE_LEVEL[c.type] for c in changes)
    final = Option(id=option.id, label=option.label, change_level=level, changes=changes, rationale=option.rationale)
    # Dropping changes can't make an option break a rule, but check anyway: the governor has the last word.
    if governor_check(final, s, ctx.athlete, ctx.library, block or {}):
        final = Option(id="hold", label="Hold: no change", change_level=0, changes=[])
        ctx.notes.append("The trimmed option failed the rules check, so the week is a hold.")

    # Every number in the words must be in the data.
    allowed = numbers.allowed_numbers(state["facts"], [c.model_dump(by_alias=True) for c in option.changes])
    rationale, dropped = numbers.filter_grounded([*final.rationale, *verdict.reasons], allowed)
    mind, dropped2 = numbers.filter_grounded(verdict.would_change_mind, allowed)
    for c in final.changes:
        if numbers.ungrounded(c.reason, allowed):
            dropped.append(c.reason)
            c.reason = f"{c.type} change on {c.exercise} (the reason given cited numbers not in your data)"
    if dropped or dropped2:
        ctx.notes.append(f"{len(dropped) + len(dropped2)} statement(s) dropped because they cited numbers not in your data.")
    summary = (state["assessment"].summary if isinstance(state.get("assessment"), Assessment) else "") or ""
    head = "Hold: no change this week." if not final.changes else f"{option.label}."
    summary = f"{head} {summary}".strip()
    if numbers.ungrounded(summary, allowed):
        summary = head
        ctx.notes.append("The summary cited numbers not in your data, so it was shortened.")
    return {
        "decision": Decision(
            recommendation="change" if final.changes else "hold",
            change_level=final.change_level,
            summary=summary,
            changes=final.changes,
            rationale=rationale,
            would_change_mind=mind,
            block=_block(block),
        )
    }


def failsafe(state: State, ctx: Context) -> State:
    return {"decision": Decision(recommendation="none", change_level=0, summary=f"No recommendation this week: {state.get('error', 'an error')}"), "failed": True}


def render(state: State, ctx: Context) -> State:
    from .render import render_report

    return {"report_md": render_report(state, ctx)}


def publish(state: State, ctx: Context) -> State:
    from .prompts import prompt_version

    s: Optional[Snapshot] = state.get("snapshot")
    payload = {
        "as_of": s.meta.as_of if s else ctx.as_of,
        "months": s.meta.months if s else ctx.months,
        "schema_version": s.meta.schema_version if s else "1",
        "snapshot_hash": s.meta.fingerprint if s else "",
        "content_md": state["report_md"],
        "decision": state["decision"].to_payload(),
        "model": getattr(ctx.llm, "model", ""),
        "prompt_version": f"{prompt_version()}+{REWARD_VERSION}",
    }
    out: State = {"payload": payload}
    if ctx.publish and payload["as_of"]:
        out["published"] = ctx.publish(payload)
    return out


def _block(block: Optional[dict]) -> Optional[dict]:
    if not block or block.get("block_number") is None:
        return None
    return {"number": block["block_number"], "week": block["week_in_block"]}


# ---------- Routes ----------


def _after_gate(state: State) -> str:
    return "finalize" if state.get("skip_reason") else "analyst"


def _after_governor(state: State) -> str:
    recommended = state["options"].recommended_option_id
    changes_pass = any(o.id != "hold" for o in state["passing"])
    if not changes_pass and recommended != "hold" and state.get("planner_tries", 0) < MAX_PLANNER_TRIES:
        return "planner"
    return "score"


def _after_critic(state: State) -> str:
    return "planner" if state["verdict"].verdict == "revise" else "finalize"


NODES: dict[str, Callable[[State, Context], State]] = {
    "load": load,
    "check": check,
    "facts": facts,
    "gate": gate,
    "analyst": analyst,
    "planner": planner,
    "governor": governor,
    "score": score,
    "critic": critic,
    "finalize": finalize,
    "failsafe": failsafe,
    "render": render,
    "publish": publish,
}

ROUTES: dict[str, str | Callable[[State], str]] = {
    "load": "check",
    "check": "facts",
    "facts": "gate",
    "gate": _after_gate,
    "analyst": "planner",
    "planner": "governor",
    "governor": _after_governor,
    "score": "critic",
    "critic": _after_critic,
    "finalize": "render",
    "failsafe": "render",
    "render": "publish",
    "publish": END,
}

START = "load"


def guarded(name: str, fn: Callable[[State, Context], State]) -> Callable[[State, Context], State]:
    """Run a node; on any error, record it so the route sends the run to the failsafe (render and publish never fail over)."""

    def run(state: State, ctx: Context) -> State:
        try:
            return fn(state, ctx)
        except Exception as e:  # noqa: BLE001 - every failure becomes an honest report
            if name in ("render", "publish"):
                raise
            return {"error": f"{name}: {e}", "trace": traceback.format_exc(limit=3)}

    return run


def next_node(name: str, state: State) -> str:
    if state.get("error") and name not in ("failsafe", "render", "publish"):
        return "failsafe"
    route = ROUTES[name]
    return route(state) if callable(route) else route
