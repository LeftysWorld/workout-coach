"""The governor: your rules, in code. The planner proposes, the governor checks, nothing an agent says
can talk its way past a rule here. A failed check goes back to the planner with the reason; after
two tries the week is a hold.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Optional

from .decision import TYPE_LEVEL, Change, Option
from .metrics import estimate_minutes
from .profile import Athlete, Library, step_for
from .snapshot import Snapshot

STRUCTURAL = {"swap", "add", "remove"}
INCREASES = {"reps", "load", "sets"}


@dataclass
class Violation:
    code: str
    message: str
    change: Optional[int] = None

    def __str__(self) -> str:
        where = f" (change {self.change + 1})" if self.change is not None else ""
        return f"[{self.code}]{where} {self.message}"


def _key(s: str) -> str:
    return " ".join(s.strip().lower().split())


def apply_changes(snapshot: Snapshot, changes: list[Change]) -> dict[str, list[dict]]:
    """The plan each workout would have after these changes: title → exercises (as dicts)."""
    plans = {w.title: [e.model_dump(exclude_none=True) for e in w.exercises] for w in snapshot.program.workouts}
    plans = copy.deepcopy(plans)
    for c in changes:
        w = snapshot.workout(c.action_id or c.workout) or snapshot.workout(c.workout)
        if not w:
            continue
        plan = plans[w.title]
        idx = next((i for i, e in enumerate(plan) if _key(e["name"]) == _key(c.exercise)), None)
        to = c.to.model_dump(exclude_none=True) if c.to else {}
        if c.type == "remove":
            if idx is not None:
                plan.pop(idx)
        elif c.type == "add":
            plan.append({"name": to.get("name", c.exercise), "sets": to.get("sets", 3), "reps_min": to.get("reps_min", 8), "reps_max": to.get("reps_max", 12), "weight": to.get("weight"), "rest": to.get("rest", "90 sec"), "note": to.get("note", "")})
        elif idx is not None:
            if c.type == "swap" and "name" in to:
                plan[idx] = {**plan[idx], "note": "", **to}
            else:
                plan[idx] = {**plan[idx], **{k: v for k, v in to.items() if k != "name"}}
    return plans


def check(option: Option, snapshot: Snapshot, athlete: Athlete, library: Library, block: dict) -> list[Violation]:
    out: list[Violation] = []
    changes = option.changes

    # Levels: a hold has no changes; the option's level is the size of its biggest change.
    if option.change_level == 0 and changes:
        out.append(Violation("hold_with_changes", "A hold (level 0) can't carry changes."))
    if option.change_level > 0 and not changes:
        out.append(Violation("change_without_changes", f"Level {option.change_level} needs at least one change."))
    biggest = max((TYPE_LEVEL[c.type] for c in changes), default=0)
    if changes and option.change_level < biggest:
        out.append(Violation("level_too_low", f"The option says level {option.change_level} but a change in it is level {biggest}."))
    if option.change_level == 6 and not any(c.type in STRUCTURAL | {"program"} for c in changes):
        out.append(Violation("program_without_structure", "A new program (level 6) must change which exercises you do."))
    if option.change_level == 5 and not any(c.type == "deload" for c in changes):
        out.append(Violation("deload_without_deload", "A lighter week (level 5) needs deload changes."))

    pain = {_key(m.exercise) for m in snapshot.metrics.exercises if m.pain_flags_4w > 0}
    structural = [i for i, c in enumerate(changes) if c.type in STRUCTURAL]
    pain_driven = all(_key(changes[i].exercise) in pain for i in structural) if structural else False

    for i, c in enumerate(changes):
        w = snapshot.workout(c.action_id or c.workout) or snapshot.workout(c.workout)
        if not w:
            out.append(Violation("unknown_workout", f"No workout called {c.workout!r}.", i))
            continue
        current = next((e for e in w.exercises if _key(e.name) == _key(c.exercise)), None)
        if c.type != "add" and current is None:
            out.append(Violation("unknown_exercise", f"{c.exercise!r} isn't in {w.title}.", i))
            continue
        to = c.to.model_dump(exclude_none=True) if c.to else {}
        if c.type in {"reps", "load", "sets", "swap", "add", "deload", "rest"} and not to:
            out.append(Violation("no_target", f"A {c.type} change needs the new values in 'to'.", i))

        # Pain: never push an exercise that hurt. Remove it, swap it, or make it lighter.
        if _key(c.exercise) in pain and c.type in INCREASES and current is not None:
            up = (c.type == "load" and (to.get("weight") or 0) > (current.weight or 0)) or (c.type == "sets" and (to.get("sets") or 0) > current.sets) or (c.type == "reps" and (to.get("reps_max") or 0) > current.reps_max)
            if up:
                out.append(Violation("pain_progressed", f"{c.exercise} has pain flags: it can be removed, swapped or eased, not pushed.", i))

        # Load: one smallest step, and no jump bigger than the limit (add reps or a set instead).
        if c.type == "load" and current is not None and "weight" in to:
            lib = library.find(c.exercise)
            step = step_for(lib, athlete) or athlete.increments.dumbbell
            old, new = current.weight, to["weight"]
            if old and new > old:
                if new - old > step + 1e-9:
                    out.append(Violation("load_jump_too_big", f"{c.exercise}: {old:g} → {new:g} is more than one {step:g} {athlete.units} step.", i))
                if (new - old) / old > athlete.increments.max_jump_pct + 1e-9:
                    out.append(Violation("load_jump_pct", f"{c.exercise}: {old:g} → {new:g} is a {round((new - old) / old * 100)}% jump (limit {round(athlete.increments.max_jump_pct * 100)}%). Add reps or a set instead.", i))

        if c.type in {"reps", "sets", "swap", "add", "deload"}:
            sets = to.get("sets", current.sets if current else 3)
            lo = to.get("reps_min", current.reps_min if current else 8)
            hi = to.get("reps_max", current.reps_max if current else 12)
            if not (1 <= sets <= 6):
                out.append(Violation("bad_sets", f"{sets} sets is outside 1–6.", i))
            if lo > hi or hi > 30 or lo < 1:
                out.append(Violation("bad_reps", f"Reps {lo}–{hi} don't make sense.", i))

        # New exercises: from the library, and inside every rule.
        if c.type in {"swap", "add"}:
            name = to.get("name") or (c.exercise if c.type == "add" else None)
            if not name:
                out.append(Violation("swap_without_name", "A swap needs the new exercise's name in to.name.", i))
            else:
                out.extend(_allowed(name, athlete, library, i))

    # At most one exercise changed per week, unless it's a block's end, you asked, or pain forced it.
    if len(structural) > 1 and option.change_level < 6 and not (block.get("at_block_end") or athlete.program.requested_program_change or pain_driven):
        out.append(Violation("too_many_swaps", f"{len(structural)} exercises added, removed or swapped; at most one a week mid-block."))

    # A few changes a week, and volume that grows slowly (a new program or a lighter week is planned as a whole).
    if option.change_level < 5:
        limit = athlete.changes.max_changes_per_week
        if len(changes) > limit and not pain_driven_all(changes, pain):
            out.append(Violation("too_many_changes", f"{len(changes)} changes in one week; at most {limit} mid-block. Pick the ones the data supports best."))
        added = 0
        for c in changes:
            w = snapshot.workout(c.action_id or c.workout) or snapshot.workout(c.workout)
            cur = next((e for e in (w.exercises if w else []) if _key(e.name) == _key(c.exercise)), None)
            if c.type == "sets" and c.to and c.to.sets is not None and cur is not None:
                added += max(0, c.to.sets - cur.sets)
            if c.type == "add":
                added += (c.to.sets if c.to and c.to.sets else 3)
        if added > athlete.changes.max_added_sets_per_week:
            out.append(Violation("too_much_volume", f"{added} sets added across the week; at most {athlete.changes.max_added_sets_per_week}."))

    # A new program needs time on the old one first.
    if option.change_level == 6:
        since = block.get("weeks_since_program_change")
        if not athlete.program.requested_program_change and since is not None and since < athlete.program.min_weeks_between_program_changes:
            out.append(Violation("program_too_soon", f"The program last changed {since} weeks ago; at least {athlete.program.min_weeks_between_program_changes} weeks between new programs."))

    # Every workout stays inside your time and exercise count.
    if changes:
        plans = apply_changes(snapshot, changes)
        for title, plan in plans.items():
            before = snapshot.workout(title)
            touched = any(_key(c.workout) == _key(title) or (c.action_id and before and c.action_id == before.action_id) for c in changes)
            if not touched:
                continue
            minutes = estimate_minutes(plan)
            limit = athlete.schedule.session_minutes.max
            if athlete.preferences.keep_duration_steady and minutes > limit and (before is None or minutes > before.estimated_minutes):
                out.append(Violation("too_long", f"{title} would take about {minutes} min (limit {limit})."))
            n = len(plan)
            had = len(before.exercises) if before else n
            rng = athlete.schedule.exercises_per_workout
            removed = [c.exercise for c in changes if c.type == "remove" and _key(c.workout) == _key(title)]
            # Removing an exercise that hurt is always allowed, even from a short workout.
            pain_removal = bool(removed) and all(_key(x) in pain for x in removed)
            if n > rng.max and n > had:
                out.append(Violation("exercise_count", f"{title} would have {n} exercises (keep it {rng.min}–{rng.max})."))
            if n < rng.min and n < had and not pain_removal:
                out.append(Violation("exercise_count", f"{title} would drop to {n} exercises (keep it {rng.min}–{rng.max})."))
    return out


def pain_driven_all(changes: list[Change], pain: set[str]) -> bool:
    """Every change is easing or removing something that hurt."""
    return bool(changes) and all(_key(c.exercise) in pain and c.type in {"remove", "swap", "load", "sets", "reps", "deload"} for c in changes)


def _allowed(name: str, athlete: Athlete, library: Library, i: int) -> list[Violation]:
    lib = library.find(name)
    if lib is None:
        return [Violation("not_in_library", f"{name!r} isn't in profile/exercise_library.yaml; only listed exercises can be suggested.", i)]
    out: list[Violation] = []
    if _key(name) in athlete.banned_exercises:
        out.append(Violation("banned_exercise", f"{name} is on your banned list.", i))
    if lib.pattern in athlete.banned_patterns or lib.knee == "loads":
        out.append(Violation("knee", f"{name} loads the knee ({lib.pattern}).", i))
    if athlete.preferences.one_cable_at_a_time and lib.cables > 1:
        out.append(Violation("two_cables", f"{name} needs {lib.cables} cable stacks; only one is free.", i))
    missing = [e for e in lib.equipment if e not in athlete.equipment]
    if missing:
        out.append(Violation("equipment", f"{name} needs {', '.join(missing)}.", i))
    return out
