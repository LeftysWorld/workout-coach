"""The reward function: fixed weights you own, never chosen by an agent.

    score = 0.35 attendance + 0.30 progression + 0.15 quality + 0.10 balance − 0.10 risk

Used twice:
- `option_score`: before the critic sees the options, each gets an expected score for next week.
  Change has to buy enough progression to cover what it costs in adherence and risk.
- `week_score`: after the fact, a week's actual score from its snapshot. The backtest and the weekly
  monitoring use it to grade the system ("did the weeks after a change score better?").

Bump REWARD_VERSION whenever a weight or a rule here changes, so old and new scores aren't compared.
"""

from __future__ import annotations

from .decision import Option
from .profile import Athlete

REWARD_VERSION = "r2"
WEIGHTS = {"attendance": 0.35, "progression": 0.30, "quality": 0.15, "balance": 0.10, "risk": 0.10}
PRIORITY_MUSCLES = ["lats", "chest", "upper_chest", "side_delts", "biceps", "upper_back", "lower_back"]
# Hard sets per priority muscle per week that count as "enough" (a plain target, not a claim about optimum).
SETS_TARGET = 8


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def option_score(option: Option, facts: dict, athlete: Athlete) -> float:
    """Expected score of next week under this option, 0–1. A hold scores the current trajectory."""
    by_name = {e["exercise"].strip().lower(): e for e in facts.get("exercises", [])}
    attendance = facts.get("attendance", {}).get("attendance_4w") or 0.8
    changes = option.changes
    structural = sum(1 for c in changes if c.type in {"swap", "add", "remove", "program"})

    # Attendance: big changes cost some adherence, more so when attendance is already shaky.
    shaky = 1.0 if attendance < 0.8 else 0.5
    att = _clip(attendance - shaky * (0.03 * structural + (0.08 if option.change_level >= 6 else 0)))

    # Progression: credit for acting on exercises that are ready or stuck; holding them costs a little.
    ready = [k for k, e in by_name.items() if (e.get("top_of_range_streak") or 0) >= 2 or ((e.get("avg_rir_2w") or 0) >= 3 and (e.get("sessions") or 0) >= 3)]
    stuck = [k for k, e in by_name.items() if e.get("stalled")]
    touched = {c.exercise.strip().lower(): c for c in changes}
    # Share of the lifts that need action that get it, with diminishing returns: acting on the most
    # important one or two buys most of the value; touching everything doesn't score higher.
    needs = ready + stuck
    addressed = sum(1 for k in ready if k in touched and touched[k].type in {"reps", "load", "sets"}) + sum(1 for k in stuck if k in touched and touched[k].type in {"swap", "sets", "reps", "deload"})
    if needs:
        share = addressed / len(needs)
        prog = 0.5 + 0.35 * min(1.0, share * 2) if addressed else 0.5 - 0.05 * min(len(needs), 3)
    else:
        prog = 0.6
    if option.change_level >= 6 and len(stuck) >= max(2, len(by_name) // 2):
        prog = max(prog, 0.85)  # a stale program is what a new program is for
    for k, c in touched.items():
        if k not in ready and k not in stuck and c.type in {"load", "swap"}:
            prog -= 0.05  # changing what's working
    prog = _clip(prog)

    # Quality: sets landing in range at the intended effort; a load jump on a near-limit lift hurts it.
    quality = facts.get("attendance", {}).get("set_completion_4w") or 0.9
    for c in changes:
        e = by_name.get(c.exercise.strip().lower())
        if e and c.type == "load" and (e.get("avg_rir_2w") is not None and e["avg_rir_2w"] < 1):
            quality -= 0.1
    quality = _clip(quality)

    # Balance: adding sets for a priority muscle under target helps; removing them hurts.
    sets = facts.get("muscle_sets_per_week", {})
    balance = _clip(sum(min(1.0, sets.get(m, 0) / SETS_TARGET) for m in PRIORITY_MUSCLES) / len(PRIORITY_MUSCLES))
    for c in changes:
        e = by_name.get(c.exercise.strip().lower())
        muscles = set((e or {}).get("muscles") or [])
        if c.type == "sets" and c.to and c.from_ and (c.to.sets or 0) > (c.from_.sets or 0) and muscles & set(PRIORITY_MUSCLES):
            balance = _clip(balance + 0.05)

    # Risk: pain, big jumps, many changes at once, a new program soon after the last.
    # Many changes at once: harder to stick to, impossible to tell what worked.
    risk = 0.05 * len(changes) + 0.1 * max(0, len(changes) - 2)
    for c in changes:
        e = by_name.get(c.exercise.strip().lower())
        if e and (e.get("pain_flags_4w") or 0) > 0 and c.type in {"load", "reps", "sets"}:
            risk += 0.5
        if e and c.type == "load" and e.get("jump_too_big"):
            risk += 0.3
    since = (facts.get("block") or {}).get("weeks_since_program_change")
    if option.change_level >= 6 and since is not None and since < athlete.program.min_weeks_between_program_changes:
        risk += 0.4
    risk = _clip(risk)

    w = WEIGHTS
    return round(w["attendance"] * att + w["progression"] * prog + w["quality"] * quality + w["balance"] * balance - w["risk"] * risk, 4)


def week_score(snapshot) -> dict:
    """A week's actual score from its snapshot (as of the week's end). Components are kept for the dashboard."""
    m = snapshot.metrics
    attendance = m.attendance_4w if m.attendance_4w is not None else 0.0
    rated = [e for e in m.exercises if e.e1rm_trend_pct is not None]
    cutting = bool(snapshot.bodyweight.shared and (snapshot.bodyweight.trend_per_week or 0) < -0.5)
    # Losing weight: holding strength counts as progress. Otherwise it has to go up.
    floor = -1.0 if cutting else 0.5
    progression = sum(1 for e in rated if e.e1rm_trend_pct >= floor) / len(rated) if rated else 0.5
    rirs = [e.avg_rir_2w for e in m.exercises if e.avg_rir_2w is not None]
    on_target = sum(1 for r in rirs if 1 <= r <= 2) / len(rirs) if rirs else None
    quality = _clip(((m.set_completion_4w or 0) + (on_target if on_target is not None else (m.set_completion_4w or 0))) / 2)
    pain = sum(1 for e in m.exercises if e.pain_flags_4w > 0)
    risk = _clip(0.25 * pain)
    balance = 0.5
    w = WEIGHTS
    total = w["attendance"] * attendance + w["progression"] * progression + w["quality"] * quality + w["balance"] * balance - w["risk"] * risk
    return {"version": REWARD_VERSION, "score": round(total, 4), "attendance": attendance, "progression": round(progression, 3), "quality": round(quality, 3), "balance": balance, "risk": risk, "cutting": cutting}
