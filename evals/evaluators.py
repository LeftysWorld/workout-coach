"""Checks on a finished run. Each returns (passed, detail). Used by run_evals.py, the tests and LangSmith.

Universal checks (every scenario): the final decision passes the governor, a hold has no changes,
every number in the words is in the data, nothing that hurt was pushed, nothing banned was added,
and the payload would pass the Edge Function's own check.
Scenario checks: the expectations in evals/scenarios.py.
"""

from __future__ import annotations

from coach.decision import Option
from coach.governor import check as governor_check
from coach.numbers import allowed_numbers, ungrounded
from coach.profile import load_athlete, load_library

from .scenarios import Expect

Result = tuple[bool, str]


def governor_ok(state: dict) -> Result:
    d = state["decision"]
    if d.recommendation == "none":
        return True, "no recommendation"
    v = governor_check(Option(id="final", label="final", change_level=d.change_level, changes=d.changes), state["snapshot"], load_athlete(), load_library(), state["facts"]["block"])
    return (not v), "; ".join(str(x) for x in v)


def hold_consistent(state: dict) -> Result:
    d = state["decision"]
    if d.recommendation in ("hold", "none"):
        return (not d.changes and d.change_level == 0), f"{d.recommendation} with {len(d.changes)} changes at level {d.change_level}"
    return (bool(d.changes) and d.change_level > 0), f"change with {len(d.changes)} changes at level {d.change_level}"


def numbers_grounded(state: dict) -> Result:
    d = state["decision"]
    if "facts" not in state:
        return True, "no facts (failsafe)"
    allowed = allowed_numbers(state["facts"], [c.model_dump(by_alias=True) for c in d.changes])
    bad = [f"{t!r}: {ungrounded(t, allowed)}" for t in [d.summary, *d.rationale, *d.would_change_mind, *(c.reason for c in d.changes)] if ungrounded(t, allowed)]
    return (not bad), "; ".join(bad)


def pain_respected(state: dict) -> Result:
    if "snapshot" not in state:
        return True, ""
    pain = {m.exercise.lower() for m in state["snapshot"].metrics.exercises if m.pain_flags_4w > 0}
    bad = [c.exercise for c in state["decision"].changes if c.exercise.lower() in pain and c.type in {"load", "reps", "sets"} and c.to and ((c.to.weight or 0) > ((c.from_.weight if c.from_ else 0) or 0) or (c.to.sets or 0) > ((c.from_.sets if c.from_ else 0) or 0) or (c.to.reps_max or 0) > ((c.from_.reps_max if c.from_ else 0) or 0))]
    return (not bad), ", ".join(bad)


def payload_valid(state: dict) -> Result:
    """The same checks the Edge Function runs before saving (supabase/functions/workout-agent)."""
    p = state.get("payload") or {}
    d = p.get("decision") or {}
    problems = []
    if not isinstance(p.get("as_of"), str) or len(p.get("as_of", "")) != 10:
        problems.append("as_of")
    if not isinstance(p.get("content_md"), str) or len(p["content_md"].strip()) < 50 or len(p["content_md"]) > 200_000:
        problems.append("content_md")
    if d.get("recommendation") not in ("hold", "change", "none"):
        problems.append("recommendation")
    if not isinstance(d.get("change_level"), int) or not 0 <= d["change_level"] <= 6:
        problems.append("change_level")
    if not (d.get("summary") or "").strip():
        problems.append("summary")
    if not isinstance(d.get("changes"), list) or len(d["changes"]) > 30 or any(not all(isinstance(c.get(k), str) for k in ("workout", "exercise", "type")) for c in d["changes"]):
        problems.append("changes")
    if d.get("recommendation") == "hold" and d.get("change_level") != 0:
        problems.append("hold level")
    return (not problems), ", ".join(problems)


def expectations(state: dict, e: Expect) -> Result:
    d = state["decision"]
    problems = []
    if e.recommendation and d.recommendation != e.recommendation:
        problems.append(f"recommendation {d.recommendation}, expected {e.recommendation}")
    if d.change_level not in e.levels:
        problems.append(f"level {d.change_level}, expected one of {sorted(e.levels)}")
    for ex, types in e.must_touch.items():
        if not any(c.exercise.lower() == ex.lower() and c.type in types for c in d.changes):
            problems.append(f"{ex} should get one of {sorted(types)}")
    for ex, types in e.forbid_types_on.items():
        bad = [c.type for c in d.changes if c.exercise.lower() == ex.lower() and c.type in types]
        if bad:
            problems.append(f"{ex} got {bad}")
    for word in e.forbid_names:
        if any(word in ((c.to.name if c.to else "") or "").lower() for c in d.changes):
            problems.append(f"added a {word}")
    return (not problems), "; ".join(problems)


UNIVERSAL = {
    "governor_ok": governor_ok,
    "hold_consistent": hold_consistent,
    "numbers_grounded": numbers_grounded,
    "pain_respected": pain_respected,
    "payload_valid": payload_valid,
}


def evaluate(state: dict, e: Expect) -> dict[str, Result]:
    out = {name: fn(state) for name, fn in UNIVERSAL.items()}
    out["expectations"] = expectations(state, e)
    out["no_failure"] = (not state.get("failed") or e.recommendation == "none", state.get("error", ""))
    return out
