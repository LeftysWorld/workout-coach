"""Numbers, computed by code, never by the model.

1. `check_contract`: recompute a few of the snapshot's figures from its raw sets. If the app and the
   agent disagree, the run stops: a recommendation built on numbers neither side can reproduce is
   worse than none.
2. `build_facts`: the compact view the agents read. Everything they may cite is in here, so the
   numbers check (coach/numbers.py) can hold them to it.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from .profile import Athlete, Library, step_for
from .snapshot import Snapshot, SnapshotError

DONE = {"done", "partial", "minimum"}


def d(s: str) -> date:
    return date.fromisoformat(s)


def e1rm(weight: Optional[float], reps: Optional[int]) -> Optional[float]:
    """Epley estimate, as the app computes it (null for bodyweight and past 15 reps)."""
    if weight is None or reps is None or weight <= 0 or reps <= 0 or reps > 15:
        return None
    return round(weight * (1 + reps / 30) + 1e-9, 1)


def estimate_minutes(exercises: list[dict] | list[Any]) -> int:
    """Same rule as the app: 5 minutes to warm up, then each set about 45 s of work plus its rest."""
    import re

    seconds = 5 * 60
    for ex in exercises:
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
    """Recompute estimated maxes and 4-week attendance from the raw sessions; stop on a mismatch."""
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
    counted = [x for x in s.sessions if x.action_id and x.status != "planned" and lo <= d(x.date) <= as_of]
    # The snapshot's detail window is 8 weeks, so the 4-week attendance is fully inside it.
    done = sum(1 for x in counted if x.status in DONE)
    if counted and (len(counted) != s.metrics.workouts_planned_4w or done != s.metrics.workouts_done_4w):
        problems.append(f"attendance: {s.metrics.workouts_done_4w}/{s.metrics.workouts_planned_4w} in the snapshot, {done}/{len(counted)} recomputed")
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


def build_facts(s: Snapshot, athlete: Athlete, library: Library) -> dict:
    """The compact view every agent reads. Keep it small: the full report is for you, this is for them."""
    as_of = d(s.meta.as_of)
    exercises = []
    for m in s.metrics.exercises:
        lib = library.find(m.exercise)
        step = step_for(lib, athlete)
        exercises.append(
            {
                **m.model_dump(exclude_none=True),
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
    lines = []
    for sess in recent:
        by_ex: dict[str, list] = defaultdict(list)
        for x in sess.sets:
            by_ex[x.exercise].append(x)
        sets_txt = "; ".join(
            f"{ex}: " + ", ".join(f"{'BW' if r.weight is None else _num(r.weight)}x{r.reps if r.reps is not None else '?'}{'' if r.rir is None else f'@{r.rir}'}{'' if r.done else ' (not done)'}{' PAIN' if r.pain else ''}" for r in rows)
            for ex, rows in by_ex.items()
        )
        lines.append(f"{sess.date} {sess.workout} [{sess.status}]{(' ' + str(sess.minutes) + ' min') if sess.minutes else ''}: {sets_txt}{(' | note: ' + sess.note) if sess.note else ''}")
    comments = [c.model_dump() for c in s.comments if c.source != "session_note" or (c.date and d(c.date) >= as_of - timedelta(days=27))]
    bw = s.bodyweight.model_dump() if s.bodyweight.shared else None
    if bw:
        bw["weekly"] = bw.get("weekly", [])[-8:]
    return {
        "as_of": s.meta.as_of,
        "units": s.meta.units,
        "snapshot": s.meta.fingerprint,
        "block": block_position(s, athlete),
        "attendance": {
            "attendance_4w": s.metrics.attendance_4w,
            "attendance_8w": s.metrics.attendance_8w,
            "workouts_done_4w": s.metrics.workouts_done_4w,
            "workouts_planned_4w": s.metrics.workouts_planned_4w,
            "set_completion_4w": s.metrics.set_completion_4w,
            "avg_session_minutes_4w": s.metrics.avg_session_minutes_4w,
            "weekly_sets": [w.model_dump() for w in s.metrics.weekly_sets[-8:]],
        },
        "bodyweight": bw,
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
        "exercises": exercises,
        "muscle_sets_per_week": muscle_sets(s, library),
        "last_two_weeks": lines,
        "comments": comments,
        "decisions": [x.model_dump(by_alias=True) for x in s.decisions[-6:]],
        "since_last": s.since_last.model_dump() if s.since_last else None,
    }


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
