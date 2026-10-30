"""The reward function: fixed weights you own, never chosen by an agent.

    score = 0.35 consistency + 0.30 progression + 0.15 quality + 0.10 balance − 0.10 risk

Used twice:
- `option_score`: before the critic sees the options, each gets an expected score for next week.
  Change has to buy enough progression to cover what it costs in consistency and risk.
- `week_score`: after the fact, a week's actual score from its snapshot. The backtest and the weekly
  monitoring use it to grade the system ("did the weeks after a change score better?").

Version r3 (schema 2): everything is measured against what you actually did, never the plan.
Consistency is your recent workouts per week against your own usual; progression credits acting on
lifts that are ready, stuck or too heavy (and a lighter week when the fatigue signals call for one);
quality is the share of lifts worked in the 7–9 effort range.

Bump REWARD_VERSION whenever a weight or a rule here changes, so old and new scores aren't compared.
"""

from __future__ import annotations

from .decision import Option
from .profile import Athlete

REWARD_VERSION = "r3"
WEIGHTS = {"consistency": 0.35, "progression": 0.30, "quality": 0.15, "balance": 0.10, "risk": 0.10}
PRIORITY_MUSCLES = ["lats", "chest", "upper_chest", "side_delts", "biceps", "upper_back", "lower_back"]
# Hard sets per priority muscle per week that count as "enough" (a plain target, not a claim about optimum).
SETS_TARGET = 8
EFFORT_TARGET = (7, 9)


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def option_score(option: Option, facts: dict, athlete: Athlete) -> float:
    """Expected score of next week under this option, 0–1. A hold scores the current trajectory."""
    by_name = {e["exercise"].strip().lower(): e for e in facts.get("exercises", [])}
    ps = facts.get("program_signals") or {}
    ratio = ps.get("consistency_ratio")
    consistency = min(1.0, ratio) if ratio is not None else 0.9
    changes = option.changes
    structural = sum(1 for c in changes if c.type in {"swap", "add", "remove", "program"})

    # Consistency: big changes cost some adherence, more so when you've been training less than usual.
    shaky = 1.0 if consistency < 0.8 else 0.5
    cons = _clip(consistency - shaky * (0.03 * structural + (0.08 if option.change_level >= 6 else 0)))

    # Progression: credit for acting on lifts that need it; holding them costs a little.
    ready = [k for k, e in by_name.items() if e.get("ready_to_add_weight")]
    stuck = [k for k, e in by_name.items() if e.get("stalled")]
    heavy = [k for k, e in by_name.items() if e.get("too_heavy")]
    touched = {c.exercise.strip().lower(): c for c in changes}
    needs = ready + stuck + heavy
    addressed = (
        sum(1 for k in ready if k in touched and touched[k].type in {"reps", "load", "sets"})
        + sum(1 for k in stuck if k in touched and touched[k].type in {"swap", "sets", "reps", "deload"})
        + sum(1 for k in heavy if k in touched and touched[k].type in {"load", "reps", "sets", "deload", "swap"})
    )
    if needs:
        share = addressed / len(needs)
        prog = 0.5 + 0.35 * min(1.0, share * 2) if addressed else 0.5 - 0.05 * min(len(needs), 3)
    else:
        prog = 0.6
    if option.change_level >= 6 and len(stuck) >= max(2, len(by_name) // 2):
        prog = max(prog, 0.85)  # a stale program is what a new program is for
    deload_due = bool(ps.get("deload_suggested"))
    if option.change_level == 5:
        prog = max(prog, 0.85) if deload_due else min(prog, 0.4)  # a lighter week is worth it only when you're worn down
    elif deload_due:
        prog -= 0.1  # pushing on through the fatigue signals
    for k, c in touched.items():
        if k not in ready and k not in stuck and k not in heavy and c.type in {"load", "swap"}:
            prog -= 0.05  # changing what's working
    prog = _clip(prog)

    # Quality: lifts worked in the target effort; more weight on a lift already near its limit hurts it.
    efforts = [e["avg_effort_2w"] for e in by_name.values() if e.get("avg_effort_2w") is not None]
    quality = sum(1 for x in efforts if EFFORT_TARGET[0] <= x <= EFFORT_TARGET[1]) / len(efforts) if efforts else 0.8
    for c in changes:
        e = by_name.get(c.exercise.strip().lower())
        if e and c.type == "load" and c.to and c.from_ and (c.to.weight or 0) > (c.from_.weight or 0) and (e.get("effort_last") or 0) >= 9:
            quality -= 0.1
    quality = _clip(quality)

    # Balance: adding sets for a priority muscle under target helps.
    sets = facts.get("muscle_sets_per_week", {})
    balance = _clip(sum(min(1.0, sets.get(m, 0) / SETS_TARGET) for m in PRIORITY_MUSCLES) / len(PRIORITY_MUSCLES))
    for c in changes:
        e = by_name.get(c.exercise.strip().lower())
        muscles = set((e or {}).get("muscles") or [])
        if c.type == "sets" and c.to and c.from_ and (c.to.sets or 0) > (c.from_.sets or 0) and muscles & set(PRIORITY_MUSCLES):
            balance = _clip(balance + 0.05)

    # Risk: pain, big jumps, more weight on a lift that's too heavy, many changes at once, a new program too soon.
    risk = 0.05 * len(changes) + 0.1 * max(0, len(changes) - 2)
    for c in changes:
        e = by_name.get(c.exercise.strip().lower())
        up = c.to is not None and c.from_ is not None and (((c.to.weight or 0) > (c.from_.weight or 0)) or ((c.to.sets or 0) > (c.from_.sets or 0)) or ((c.to.reps_max or 0) > (c.from_.reps_max or 0)))
        if e and (e.get("pain_flags_4w") or 0) > 0 and c.type in {"load", "reps", "sets"} and up:
            risk += 0.5
        if e and c.type == "load" and e.get("jump_too_big") and up:
            risk += 0.3
        if e and e.get("too_heavy") and c.type == "load" and up:
            risk += 0.3
    since = (facts.get("block") or {}).get("weeks_since_program_change")
    if option.change_level >= 6 and since is not None and since < athlete.program.min_weeks_between_program_changes:
        risk += 0.4
    risk = _clip(risk)

    w = WEIGHTS
    return round(w["consistency"] * cons + w["progression"] * prog + w["quality"] * quality + w["balance"] * balance - w["risk"] * risk, 4)


def week_score(snapshot) -> dict:
    """A week's actual score from its snapshot (as of the week's end). Components are kept for the dashboard."""
    m = snapshot.metrics
    weeks = m.weeks
    recent = [w.workouts for w in weeks[-2:]]
    usual = [w.workouts for w in weeks[:-2] if w.workouts > 0][-4:]
    consistency = _clip((sum(recent) / len(recent)) / (sum(usual) / len(usual))) if recent and usual else (1.0 if recent and sum(recent) else 0.0)
    rated = [e for e in m.exercises if e.e1rm_trend_pct is not None]
    cutting = bool(snapshot.bodyweight.shared and (snapshot.bodyweight.trend_per_week or 0) < -0.5)
    # Losing weight: holding strength counts as progress. Otherwise it has to go up.
    floor = -1.0 if cutting else 0.5
    progression = sum(1 for e in rated if e.e1rm_trend_pct >= floor) / len(rated) if rated else 0.5
    efforts = [e.avg_effort_2w for e in m.exercises if e.avg_effort_2w is not None]
    quality = sum(1 for x in efforts if EFFORT_TARGET[0] <= x <= EFFORT_TARGET[1]) / len(efforts) if efforts else 0.5
    pain = sum(1 for e in m.exercises if e.pain_flags_4w > 0)
    risk = _clip(0.25 * pain)
    balance = 0.5
    w = WEIGHTS
    total = w["consistency"] * consistency + w["progression"] * progression + w["quality"] * quality + w["balance"] * balance - w["risk"] * risk
    return {"version": REWARD_VERSION, "score": round(total, 4), "consistency": round(consistency, 3), "progression": round(progression, 3), "quality": round(quality, 3), "balance": balance, "risk": risk, "cutting": cutting}
