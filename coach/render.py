"""The coach's report, from a fixed template (coach/templates/coach_report.md.j2).

The agents supply judgment (the reads, the reasons); the numbers come from the facts, and the layout
from the template, so every week's report has the same sections in the same order.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .decision import LEVELS, Decision, ExerciseTarget

TEMPLATES = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(TEMPLATES), undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)

READS = {
    "ready_to_progress": "ready to move up",
    "progressing": "progressing",
    "holding": "holding",
    "stalled": "stalled",
    "too_heavy": "too heavy now",
    "regressing": "slipping",
    "pain": "⚠ pain",
    "too_early": "too early to tell",
    "not_done": "not done lately",
}


def num(v: Optional[float], digits: int = 1) -> str:
    if v is None:
        return "–"
    r = round(float(v), digits)
    return str(int(r)) if float(r).is_integer() else f"{r:.{digits}f}"


def signed(v: Optional[float], unit: str = "") -> str:
    return "–" if v is None else f"{'+' if v > 0 else ''}{num(v)}{unit}"


def pct(v: Optional[float]) -> str:
    return "–" if v is None else f"{round(v * 100)}%"


def target(t: Optional[ExerciseTarget]) -> str:
    """Only the fields that change: "Seated Cable Row", "3 sets", "12–15 reps", "50", "rest 90 sec"."""
    if t is None:
        return "–"
    parts = []
    if t.name:
        parts.append(t.name)
    if t.sets is not None:
        parts.append(f"{t.sets} sets")
    if t.reps_min is not None or t.reps_max is not None:
        lo, hi = t.reps_min, t.reps_max
        parts.append(f"{lo if hi is None or lo == hi else (hi if lo is None else f'{lo}–{hi}')} reps")
    if t.weight is not None:
        parts.append(num(t.weight))
    if t.rest:
        parts.append(f"rest {t.rest}")
    return " · ".join(parts) or "–"


def _last_time(e: dict) -> str:
    r = (e.get("recent") or [None])[-1]
    if not r:
        return "–"
    w = "BW" if r.get("weight") is None else num(r["weight"])
    return f"{w} × {', '.join(str(x) for x in r.get('reps', []))}" + (f" @{r['effort']}" if r.get("effort") is not None else "")


def _label(iso: str) -> str:
    dt = date.fromisoformat(iso)
    return f"{dt.strftime('%a %b')} {dt.day}, {dt.year}"


def render_report(state: dict, ctx: Any) -> str:
    from .prompts import prompt_version
    from .score import REWARD_VERSION

    decision: Decision = state["decision"]
    facts = state.get("facts") or {}
    snapshot = state.get("snapshot")
    as_of = snapshot.meta.as_of if snapshot else (ctx.as_of or date.today().isoformat())
    reads = {}
    assessment = state.get("assessment")
    if assessment is not None:
        reads = {r.exercise.strip().lower(): READS.get(r.verdict, r.verdict) for r in assessment.exercises}
    keys = ("last_weight", "e1rm_now", "e1rm_trend_pct", "weeks_since_gain", "avg_effort_2w")
    exercises = [{**{k: None for k in keys}, **e, "last_time": _last_time(e), "read": reads.get(e["exercise"].strip().lower(), "–")} for e in facts.get("exercises", []) if e.get("workouts")]

    if decision.recommendation == "none":
        headline = "No recommendation this week"
    elif decision.recommendation == "hold":
        headline = "Hold: keep next week the same"
    else:
        headline = f"Change: {LEVELS.get(decision.change_level, f'level {decision.change_level}')}"

    option_lines = []
    chosen = getattr(state.get("verdict"), "chosen_option_id", None)
    scores = state.get("scores", {})
    rejected_last = {k.split(":", 1)[1]: v for k, v in state.get("rejected", {}).items() if k.startswith(f"try{state.get('planner_tries', 1)}:")}
    if state.get("options") is not None:
        for o in state["options"].options:
            line = f"**{o.label}** (level {o.change_level}"
            line += f", score {scores[o.id]:.3f})" if o.id in scores else ")"
            if o.id == chosen:
                line += " ← chosen"
            if rejected_last.get(o.id):
                line += f" · failed the rules check: {'; '.join(rejected_last[o.id])}"
            option_lines.append(line)
    verdict = state.get("verdict")
    if verdict is not None and option_lines:
        word = {"accept": "accepted it", "downgrade": "downgraded it", "revise": "asked for a revision"}[verdict.verdict]
        option_lines.append(f"The critic {word}" + (f" (dropped: {', '.join(verdict.drop_exercises)})" if verdict.drop_exercises else "") + ".")

    notes = list(getattr(ctx, "notes", []))
    if state.get("planner_tries", 0) > 1:
        notes.append(f"The planner needed {state['planner_tries']} tries to stay inside your rules.")
    if state.get("error"):
        notes.append(f"Stopped at {state['error']}")

    footer = " · ".join(
        x
        for x in [
            f"as of {as_of}",
            f"snapshot {snapshot.meta.fingerprint}" if snapshot else None,
            f"model {getattr(ctx.llm, 'model', '?')}",
            f"prompts {prompt_version()}",
            f"reward {REWARD_VERSION}",
        ]
        if x
    )
    act = facts.get("activity") or {}
    ps = facts.get("program_signals") or {}
    block = facts.get("block") or {}
    glance = [("Workouts done, last 4 weeks", str(act.get("workouts_done_4w", "–")))]
    if ps.get("workouts_per_week_recent") is not None:
        glance.append(("Workouts a week", f"{num(ps['workouts_per_week_recent'])} lately" + (f" · {num(ps['workouts_per_week_usual'])} usually" if ps.get("workouts_per_week_usual") is not None else "")))
    if ps.get("workout_effort_recent") is not None:
        glance.append(("Whole-workout effort", f"{num(ps['workout_effort_recent'])} lately" + (f" · {num(ps['workout_effort_usual'])} usually" if ps.get("workout_effort_usual") is not None else "")))
    if ps.get("deload_signals"):
        glance.append(("Signs you need a lighter week", "; ".join(ps["deload_signals"])))
    if block.get("program_age_weeks") is not None:
        glance.append(("Program", f"{block['program_age_weeks']} weeks old · block {block['block_number']}, week {block['week_in_block']} of {ctx.athlete.program.block_weeks}" + (" (the block ends: bigger changes are on the table)" if block.get("at_block_end") else "")))
    bw = facts.get("bodyweight")
    if bw:
        latest = bw.get("latest")
        glance.append(("Body weight", (f"{num(latest['value'])} {bw['unit']}" if latest else "–") + (f" · {signed(bw.get('trend_per_week'))} {bw['unit']}/week" if bw.get("trend_per_week") is not None else "")))
    for b in facts.get("body_measurements") or []:
        latest = b.get("latest")
        glance.append((b["name"], (f"{num(latest['value'], 2)} {b['unit']}" if latest else "–") + (f" · {signed(b.get('change_4w'))} {b['unit']} over 4 weeks" if b.get("change_4w") is not None else "")))
    return _env.get_template("coach_report.md.j2").render(
        as_of_label=_label(as_of),
        headline=headline,
        decision=decision,
        glance=glance,
        exercises=exercises,
        assessment=assessment,
        option_lines=option_lines,
        notes=notes,
        change_list=json.dumps(decision.to_payload(), indent=2, ensure_ascii=False),
        footer=footer,
        num=num,
        signed=signed,
        pct=pct,
        target=target,
    )
