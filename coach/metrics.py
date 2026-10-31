"""Numbers, computed by code, never by the model.

1. `check_contract`: recompute a few of the snapshot's figures from its raw sets. If the app and the
   agent disagree, the run stops: a recommendation built on numbers neither side can reproduce is
   worse than none.
2. `exercise_signals` and `program_signals`: what the history says, worked out in code from what you
   actually did (weight, reps, effort 1–10, pain), never from the plan's targets: ready for more
   weight, too heavy, getting harder at the same load, a lighter week due, how long on an exercise.
3. `build_facts`: the compact view the agents read. Everything they may cite is in here, so the
   numbers check (coach/numbers.py) can hold them to it. `analyst_view` is the same without the
   plan: the analyst judges from what happened; only the planner sees the plan, to write changes.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from .profile import Athlete, Library, step_for
from .snapshot import ExerciseMetrics, Snapshot, SnapshotError

DONE = {"done", "partial", "minimum"}


def d(s: str) -> date:
    return date.fromisoformat(s)


def e1rm(weight: Optional[float], reps: Optional[int]) -> Optional[float]:
    """Epley estimate, as the app computes it (null for bodyweight and past 15 reps)."""
    if weight is None or reps is None or weight <= 0 or reps <= 0 or reps > 15:
        return None
    return round(weight * (1 + reps / 30) + 1e-9, 1)


def estimate_minutes(exercises: list[dict] | list[Any]) -> int:
    """Same rule as the app: 5 minutes to warm up, then each set about 45 s of work plus its rest.
    In a superset (exercises sharing a `superset` label) you rest after the round, not between its moves."""
    import re

    def field(ex, k):
        return ex.get(k) if isinstance(ex, dict) else getattr(ex, k, None)

    seconds = 5 * 60
    items = list(exercises)
    for i, ex in enumerate(items):
        label = field(ex, "superset")
        if label and i + 1 < len(items) and field(items[i + 1], "superset") == label:
            seconds += int(field(ex, "sets") or 0) * 45
            continue
        rest = (ex.get("rest") if isinstance(ex, dict) else getattr(ex, "rest", "")) or ""
        sets = int(ex.get("sets") if isinstance(ex, dict) else getattr(ex, "sets", 0))
        m = re.search(r"(\d+(?:\.\d+)?)(?:\s*[–-]\s*(\d+(?:\.\d+)?))?\s*(min|m\b|minutes?|s\b|sec|seconds?)?", rest, re.I)
        if not m:
            r = 90
        else:
            lo = float(m.group(1))
            hi = float(m.group(2)) if m.group(2) else lo
            unit = (m.group(3) or "").lower()
            mins = unit.startswith("m") or (not unit and hi <= 5)
            r = round(((lo + hi) / 2) * (60 if mins else 1))
        seconds += sets * (45 + r)
    return round(seconds / 60)


def check_contract(s: Snapshot) -> None:
    """Recompute estimated maxes and the 4-week workout count from the raw sessions; stop on a mismatch."""
    as_of = d(s.meta.as_of)
    problems: list[str] = []
    for m in s.metrics.exercises:
        key = m.exercise.strip().lower()
        best: Optional[float] = None
        for sess in s.sessions:
            if not (as_of - timedelta(days=13) <= d(sess.date) <= as_of):
                continue
            for x in sess.sets:
                if x.done and x.exercise.strip().lower() == key:
                    est = e1rm(x.weight, x.reps)
                    if est is not None and (best is None or est > best):
                        best = est
        if (best is None) != (m.e1rm_now is None) or (best is not None and abs(best - (m.e1rm_now or 0)) > 0.15):
            problems.append(f"{m.exercise}: estimated max {m.e1rm_now} in the snapshot, {best} recomputed")
    lo = as_of - timedelta(days=27)
    # The snapshot's detail window is 8 weeks, so the 4-week count is fully inside it.
    done = sum(1 for x in s.sessions if x.status in DONE and lo <= d(x.date) <= as_of)
    if s.sessions and done != s.metrics.workouts_done_4w:
        problems.append(f"workouts: {s.metrics.workouts_done_4w} in the snapshot, {done} recomputed")
    if not s.meta.fingerprint:
        problems.append("the snapshot has no fingerprint")
    if problems:
        raise SnapshotError("The snapshot fails its own arithmetic: " + "; ".join(problems))


def block_position(s: Snapshot, athlete: Athlete) -> dict:
    """Where you are in the month: 4-week blocks counted from when the program last changed shape."""
    age = s.program.program_age_weeks
    weeks = athlete.program.block_weeks
    since_change = None
    if s.program.last_structural_change_on:
        since_change = (d(s.meta.as_of) - d(s.program.last_structural_change_on)).days // 7
    if age is None:
        return {"program_age_weeks": None, "block_number": None, "week_in_block": None, "at_block_end": False, "weeks_since_program_change": since_change}
    return {
        "program_age_weeks": age,
        "block_number": age // weeks + 1,
        "week_in_block": age % weeks + 1,
        "at_block_end": age % weeks + 1 == weeks,
        "weeks_since_program_change": since_change if since_change is not None else age,
        "last_structural_change_on": s.program.last_structural_change_on,
        "last_target_change_on": s.program.last_target_change_on,
    }


def muscle_sets(s: Snapshot, library: Library) -> dict[str, float]:
    """Average completed sets per muscle per week over the last two full weeks (each muscle an exercise trains counts the set)."""
    monday = d(s.meta.as_of) - timedelta(days=d(s.meta.as_of).weekday())
    weeks = {(monday - timedelta(days=7)).isoformat(), (monday - timedelta(days=14)).isoformat()}
    totals: dict[str, float] = defaultdict(float)
    for h in s.history:
        if h.week_start not in weeks:
            continue
        lib = library.find(h.exercise)
        for muscle in lib.muscles if lib else ["unknown"]:
            totals[muscle] += h.sets_done / 2
    return {k: round(v, 1) for k, v in sorted(totals.items())}


# ---------- Signals: what the history says, from what you actually did ----------

# Thresholds (the skills explain them in words). Effort is 1–10 by reps left: 8 = two left.
HEADROOM = 7  # 3+ reps left on the last set: the weight is light
TARGET_TOP = 8  # at most 2 left counts as working hard enough to call the reps real
HARD = 9  # 1 or 0 left
STRENGTH_DROP_PCT = -3.0
DELOAD_MIN_SIGNALS = 2


def _at_weight(m: ExerciseMetrics) -> list:
    """The recent workouts of an exercise at its current top weight, oldest first."""
    if not m.recent:
        return []
    w = m.recent[-1].weight
    out = []
    for r in reversed(m.recent):
        if r.weight != w:
            break
        out.append(r)
    return list(reversed(out))


def exercise_signals(m: ExerciseMetrics, as_of: Optional[date] = None) -> dict:
    """Per exercise, from the workouts as done. Booleans and differences only; the agents judge."""
    at = _at_weight(m)
    total = lambda r: sum(r.reps)  # noqa: E731
    reps_change = total(at[-1]) - total(at[0]) if len(at) >= 2 else None
    last_step = total(at[-1]) - total(at[-2]) if len(at) >= 2 else None
    rated = [r.effort for r in at if r.effort is not None]
    effort_change = (at[-1].effort - at[0].effort) if len(at) >= 2 and at[-1].effort is not None and at[0].effort is not None else None
    hurt = m.pain_flags_4w > 0
    last2 = at[-2:]
    ready = (
        not hurt
        and len(last2) == 2
        and all(r.effort is not None and r.effort <= TARGET_TOP for r in last2)
        and (last_step or 0) >= 0
        and (last2[-1].effort <= HEADROOM or (reps_change or 0) > 0)  # type: ignore[operator]
    )
    too_heavy = len(at) >= 2 and (last_step or 0) < 0 and (m.effort_last or 0) >= HARD
    getting_harder = len(at) >= 2 and (effort_change or 0) >= 1 and (reps_change or 0) <= 0 and not too_heavy
    first = d(m.first_seen) if m.first_seen else None
    return {
        "sessions_at_weight": m.sessions_at_weight,
        "reps_change_at_weight": reps_change,
        "effort_change_at_weight": effort_change,
        "rated_at_weight": len(rated),
        "ready_to_add_weight": ready,
        "too_heavy": too_heavy,
        "getting_harder": getting_harder,
        "strength_falling": (m.e1rm_trend_pct is not None and m.e1rm_trend_pct <= STRENGTH_DROP_PCT),
        "weeks_on_exercise": ((as_of - first).days // 7) if first and as_of else None,
    }


def program_signals(s: Snapshot, per_exercise: dict[str, dict]) -> dict:
    """The whole picture: consistency against your own recent average, fatigue, the pace of the cut."""
    weeks = s.metrics.weeks
    recent = weeks[-2:]
    usual = [w for w in weeks[:-2] if w.workouts > 0][-4:]
    recent_pw = round(sum(w.workouts for w in recent) / len(recent), 1) if recent else None
    usual_pw = round(sum(w.workouts for w in usual) / len(usual), 1) if usual else None
    ratio = round(recent_pw / usual_pw, 2) if recent_pw is not None and usual_pw else None
    eff_recent = [w.avg_effort for w in recent if w.avg_effort is not None]
    eff_usual = [w.avg_effort for w in weeks[:-2] if w.avg_effort is not None][-4:]
    eff_r = round(sum(eff_recent) / len(eff_recent), 1) if eff_recent else None
    eff_u = round(sum(eff_usual) / len(eff_usual), 1) if eff_usual else None
    harder = sorted(k for k, v in per_exercise.items() if v["getting_harder"] or v["too_heavy"])
    falling = sorted(k for k, v in per_exercise.items() if v["strength_falling"])
    loss_pct = None
    if s.bodyweight.shared and s.bodyweight.trend_per_week is not None and s.bodyweight.latest:
        loss_pct = round(-s.bodyweight.trend_per_week / s.bodyweight.latest.value * 100, 2)
    signals = []
    if len(harder) >= 3:
        signals.append("the same weights feel harder on several lifts")
    if len(falling) >= 2:
        signals.append("estimated strength falling on several lifts")
    if eff_r is not None and ((eff_u is not None and eff_r - eff_u >= 1.5) or eff_r >= 9):
        signals.append("whole workouts rated harder than usual")
    if ratio is not None and ratio < 0.75:
        signals.append("fewer workouts than your usual")
    if loss_pct is not None and loss_pct > 1.0:
        signals.append("losing weight faster than 1% a week")
    return {
        "workouts_per_week_recent": recent_pw,
        "workouts_per_week_usual": usual_pw,
        "consistency_ratio": ratio,
        "workout_effort_recent": eff_r,
        "workout_effort_usual": eff_u,
        "exercises_getting_harder": harder,
        "exercises_strength_falling": falling,
        "bodyweight_loss_pct_per_week": loss_pct,
        "deload_signals": signals,
        "deload_suggested": len(signals) >= DELOAD_MIN_SIGNALS,
    }


def _line(sess) -> str:
    by_ex: dict[str, list] = defaultdict(list)
    for x in sess.sets:
        by_ex[x.exercise].append(x)
    parts = []
    for ex, rows in by_ex.items():
        sets_txt = ", ".join(f"{'BW' if r.weight is None else _num(r.weight)}x{r.reps if r.reps is not None else '?'}{'' if r.done else ' (not done)'}" for r in rows)
        log = sess.log(ex)
        extra = ""
        if log:
            extra += f" @{log.effort}" if log.effort is not None else ""
            extra += f" HURT({log.pain_where.lower()})" if log.pain and log.pain_where else (" HURT" if log.pain else "")
            extra += f' "{log.note}"' if log.note else ""
        parts.append(f"{ex}: {sets_txt}{extra}")
    head = f"{sess.date} {sess.workout} [{sess.status}]{(' ' + str(sess.minutes) + ' min') if sess.minutes else ''}{(' workout effort ' + str(sess.effort)) if sess.effort is not None else ''}"
    return f"{head}: {'; '.join(parts)}{(' | note: ' + sess.note) if sess.note else ''}"


def build_facts(s: Snapshot, athlete: Athlete, library: Library) -> dict:
    """Everything the agents read. Keep it small: the full report is for you, this is for them.

    The plan (`workouts`, `plan_notes`) is here for the planner only; `analyst_view` removes it."""
    as_of = d(s.meta.as_of)
    signals = {m.exercise: exercise_signals(m, as_of) for m in s.metrics.exercises}
    exercises = []
    for m in s.metrics.exercises:
        lib = library.find(m.exercise)
        step = step_for(lib, athlete)
        exercises.append(
            {
                **m.model_dump(exclude_none=True, exclude={"recent"}),
                "recent": [r.model_dump(exclude_none=True, exclude={"weights"}) for r in m.recent[-4:]],
                **signals[m.exercise],
                "in_library": lib is not None,
                "pattern": lib.pattern if lib else None,
                "muscles": lib.muscles if lib else [],
                "trial": bool(lib and lib.trial) or "(knee test)" in m.exercise.lower(),
                "weight_step": step or None,
                "step_pct": round(step / m.last_weight, 3) if step and m.last_weight else None,
                "jump_too_big": bool(step and m.last_weight and step / m.last_weight > athlete.increments.max_jump_pct),
            }
        )
    recent = [x for x in s.sessions if d(x.date) >= as_of - timedelta(days=13)]
    comments = [c.model_dump() for c in s.comments if c.source in ("session_note", "exercise_note") and (c.date and d(c.date) >= as_of - timedelta(days=27))]
    plan_notes = [c.model_dump() for c in s.comments if c.source in ("plan_note", "details")]
    bw = s.bodyweight.model_dump() if s.bodyweight.shared else None
    if bw:
        bw["weekly"] = bw.get("weekly", [])[-8:]
    body = [{**b.model_dump(exclude_none=True), "weekly": [w.model_dump() for w in b.weekly[-6:]]} for b in s.body_measurements]
    return {
        "as_of": s.meta.as_of,
        "units": s.meta.units,
        "snapshot": s.meta.fingerprint,
        "block": block_position(s, athlete),
        "activity": {
            "workouts_done_4w": s.metrics.workouts_done_4w,
            "days_since_last_workout": s.metrics.days_since_last_workout,
            "avg_session_minutes_4w": s.metrics.avg_session_minutes_4w,
            "weeks": [w.model_dump() for w in s.metrics.weeks],
        },
        "program_signals": program_signals(s, signals),
        "bodyweight": bw,
        "body_measurements": body,
        "exercises": exercises,
        "muscle_sets_per_week": muscle_sets(s, library),
        "last_two_weeks": [_line(x) for x in recent],
        "comments": comments,
        "decisions": [x.model_dump(by_alias=True) for x in s.decisions[-6:]],
        "since_last": s.since_last.model_dump() if s.since_last else None,
        # For the planner only: the plan as it is now, to write changes against.
        "workouts": [
            {
                "title": w.title,
                "action_id": w.action_id,
                "days": w.days,
                "planned_minutes": w.planned_minutes,
                "estimated_minutes": w.estimated_minutes,
                "current_since": w.current_since,
                "exercises": [e.model_dump(exclude_none=True) for e in w.exercises],
            }
            for w in s.program.workouts
        ],
        "plan_notes": plan_notes,
    }


PLAN_KEYS = ("workouts", "plan_notes")


def analyst_view(facts: dict) -> dict:
    """The facts without the plan: what happened, judged on its own terms."""
    return {k: v for k, v in facts.items() if k not in PLAN_KEYS}


def enough_data(s: Snapshot) -> tuple[bool, str]:
    """A recommendation needs a program and at least two weeks of logged workouts."""
    if not s.program.workouts:
        return False, "There are no workout tasks with a plan."
    done = [x for x in s.sessions if x.status in DONE]
    if len({x.week_start for x in done}) < 2:
        return False, "Fewer than two weeks of logged workouts: too early to judge anything."
    return True, ""


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"
