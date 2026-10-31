"""The three agents. Each is one structured call: what it's shown, what it must return.

- Analyst: reads what you actually did (no plan targets), returns an assessment. No proposals.
- Planner: returns 2–3 options for next week, always including a hold, each sized on the ladder.
- Critic: argues for leaving things alone. Accepts, downgrades (drops changes) or asks for one revision.
"""

from __future__ import annotations

import json

from .decision import LEVELS, Assessment, CriticVerdict, Option, Options
from .llm import LLM
from .metrics import analyst_view
from .profile import Athlete, Library
from .prompts import system_prompt


def _j(obj) -> str:
    return json.dumps(obj, indent=1, default=str, ensure_ascii=False)


def ladder_text() -> str:
    return "\n".join(f"{k}: {v}" for k, v in LEVELS.items())


def allowed_library(athlete: Athlete, library: Library) -> list[dict]:
    """The exercises the planner may pick from: in the library and inside every rule."""
    out = []
    for e in library.exercises:
        if e.knee == "loads" or e.pattern in athlete.banned_patterns or e.name.strip().lower() in athlete.banned_exercises:
            continue
        if athlete.preferences.one_cable_at_a_time and e.cables > 1:
            continue
        if any(x not in athlete.equipment for x in e.equipment):
            continue
        out.append({"name": e.name, "pattern": e.pattern, "muscles": e.muscles, "trial": e.trial})
    return out


def run_analyst(llm: LLM, facts: dict, rules_update: str = "") -> Assessment:
    user = "\n\n".join(
        [
            "Assess this week from what was actually done. Every number you write must come from the facts below.",
            "## Facts\n" + _j(analyst_view(facts)),
        ]
    )
    return llm.complete_json(agent="analyst", system=system_prompt("analyst", rules_update), user=user, schema=Assessment)


def run_planner(llm: LLM, facts: dict, assessment: Assessment, athlete: Athlete, library: Library, feedback: list[str] | None = None, critic_note: str | None = None, rules_update: str = "") -> Options:
    parts = [
        "Propose 2 or 3 options for next week. One must be id 'hold' (level 0, no changes). Use the workout titles and exercise names exactly as in the facts.",
        "## Change ladder\n" + ladder_text(),
        "## Assessment (from the analyst)\n" + _j(assessment.model_dump()),
        "## Exercises you may add or swap in (nothing else)\n" + _j(allowed_library(athlete, library)),
        "## Facts\n" + _j(facts),
    ]
    if feedback:
        parts.insert(1, "## Your last proposal broke these rules. Fix them or drop those changes.\n- " + "\n- ".join(feedback))
    if critic_note:
        parts.insert(1, "## The critic asked for a revision\n" + critic_note)
    return llm.complete_json(agent="planner", system=system_prompt("planner", rules_update), user="\n\n".join(parts), schema=Options)


def run_critic(llm: LLM, facts: dict, assessment: Assessment, options: list[Option], scores: dict[str, float], can_revise: bool, rules_update: str = "") -> CriticVerdict:
    parts = [
        "Pick the option that is worth it. The burden of proof is on change: choose 'hold' unless a change clearly earns its cost. "
        + ("You may ask for one revision." if can_revise else "No more revisions: accept or downgrade."),
        "## Options (each already passed the rules check), with scores from the fixed reward function\n" + _j([{**o.model_dump(by_alias=True), "score": scores.get(o.id)} for o in options]),
        "## Past decisions and what became of them\n" + _j(facts.get("decisions", [])),
        "## Where the program is\n" + _j(facts.get("block", {})),
        "## Assessment\n" + _j(assessment.model_dump()),
        "## Facts\n" + _j({k: v for k, v in analyst_view(facts).items() if k not in ("decisions",)}),
    ]
    return llm.complete_json(agent="critic", system=system_prompt("critic", rules_update), user="\n\n".join(parts), schema=CriticVerdict)
