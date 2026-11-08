"""Your rules (profile/athlete.yaml) and the exercises the coach may use (profile/exercise_library.yaml)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
PROFILE_DIR = ROOT / "profile"


class Range(BaseModel):
    min: int
    max: int


class Count(BaseModel):
    target: int
    min: int
    max: int


class Schedule(BaseModel):
    days_per_week: int
    days: list[int]
    session_minutes: Range
    exercises_per_workout: Count


class Limit(BaseModel):
    id: str
    summary: str
    banned_patterns: list[str] = []
    banned_exercises: list[str] = []
    # Most reps allowed on exercises whose name contains `match` (e.g. lateral raises at 12).
    rep_caps: list[dict] = []
    note: str = ""


class Preferences(BaseModel):
    weights_only: bool = True
    prefer_dumbbells: bool = True
    barbells_allowed: bool = False
    one_cable_at_a_time: bool = True
    keep_duration_steady: bool = True
    # Most reps on any lift except bodyweight ones (the app's Settings → Training → Most reps). 0 = no cap.
    max_reps: int = 0


class Increments(BaseModel):
    dumbbell: float = 5
    machine: float = 5
    cable: float = 5
    max_jump_pct: float = 0.10
    # Isolation lifts move in small steps (2.5 lb dumbbells, the smallest cable plate). A small step
    # bigger than iso_max_jump_pct of the weight is tempo instead (10 → 12.5 lb is fine, 5 → 7.5 isn't).
    iso_dumbbell: float = 2.5
    iso_cable: float = 2.5
    iso_max_jump_pct: float = 0.25
    # Assisted lifts: this much less assist per step (lower assist is harder).
    assist: float = 5


class ChangeLimits(BaseModel):
    max_changes_per_week: int = 3
    max_added_sets_per_week: int = 4


class ProgramRules(BaseModel):
    block_weeks: int = 4
    min_weeks_between_program_changes: int = 4
    planned_replacement: str = ""
    requested_program_change: bool = False


class Athlete(BaseModel):
    units: str = "lb"
    schedule: Schedule
    goals: list[str]
    injuries_and_limits: list[Limit]
    preferences: Preferences
    equipment: list[str]
    increments: Increments
    changes: ChangeLimits = ChangeLimits()
    program: ProgramRules

    @property
    def banned_patterns(self) -> set[str]:
        return {p for limit in self.injuries_and_limits for p in limit.banned_patterns}

    @property
    def banned_exercises(self) -> set[str]:
        return {e.strip().lower() for limit in self.injuries_and_limits for e in limit.banned_exercises}


class LibraryExercise(BaseModel):
    name: str
    pattern: str
    muscles: list[str]
    equipment: list[str]
    knee: Literal["none", "low", "loads"]
    cables: int = 0
    step: Literal["dumbbell", "machine", "cable", "none"] = "dumbbell"
    trial: bool = False


class Library(BaseModel):
    exercises: list[LibraryExercise] = Field(default_factory=list)

    def find(self, name: str) -> Optional[LibraryExercise]:
        key = _norm(name)
        return next((e for e in self.exercises if _norm(e.name) == key), None)


def _norm(name: str) -> str:
    return " ".join(name.strip().lower().split())


@lru_cache(maxsize=4)
def load_athlete(path: str | None = None) -> Athlete:
    return Athlete.model_validate(yaml.safe_load(Path(path or PROFILE_DIR / "athlete.yaml").read_text()))


@lru_cache(maxsize=4)
def load_library(path: str | None = None) -> Library:
    return Library.model_validate(yaml.safe_load(Path(path or PROFILE_DIR / "exercise_library.yaml").read_text()))


ExerciseClass = Literal["compound", "isolation", "assisted", "bodyweight"]

# The same words as the app's exerciseClass (packages/core/src/progression.ts), so the app's next
# targets and the coach agree on what kind of lift each exercise is.
_ISOLATION = re.compile(r"curl|pushdown|push-down|kick-?back|triceps|tricep|extension(?!.*back)|raise|fly|flye|rear[- ]delt|straight[- ]arm|external rotation|internal rotation|face pull|shrug|pullover", re.I)
_BODYWEIGHT = re.compile(r"crunch|sit-?up|back extension|hip extension|glute[- /]?ham|plank|hanging leg|leg raise", re.I)
_COMPOUND = re.compile(r"press|row|pull-?down|pull-?up|chin-?up|dip|squat|deadlift|lunge", re.I)


def rep_cap(name: str, athlete: "Athlete") -> Optional[int]:
    """The lowest rep cap any limit puts on this exercise, or None."""
    caps = [int(c["max"]) for limit in athlete.injuries_and_limits for c in limit.rep_caps if str(c.get("match", "")).lower() in name.lower()]
    if athlete.preferences.max_reps > 0 and exercise_class(name) != "bodyweight":
        caps.append(athlete.preferences.max_reps)
    return min(caps) if caps else None


def exercise_class(name: str) -> ExerciseClass:
    """Compound, isolation, assisted or bodyweight, from the name (the app's rule 1)."""
    if re.search(r"assisted", name, re.I):
        return "assisted"
    if _BODYWEIGHT.search(name):
        return "bodyweight"
    if _ISOLATION.search(name):
        return "isolation"
    if _COMPOUND.search(name):
        return "compound"
    return "isolation"


def load_rule(name: str, ex: Optional[LibraryExercise], athlete: Athlete) -> tuple[float, Optional[float]]:
    """The load step for an exercise and the largest jump allowed as a share of its weight (None: no limit).

    Compound and bodyweight: one standard step (5 lb dumbbells, one plate), no percentage limit; that's the
    whole step. Isolation: the small step, at most iso_max_jump_pct (bigger means tempo, not load). Assisted:
    the assist step (adding assist is easing off, so it's never an increase)."""
    cls = exercise_class(name)
    inc = athlete.increments
    if cls == "assisted":
        return inc.assist, None
    if cls == "isolation":
        if ex is not None and ex.step == "machine":
            return inc.machine, inc.iso_max_jump_pct
        if ex is not None and ex.step == "cable":
            return inc.iso_cable, inc.iso_max_jump_pct
        return inc.iso_dumbbell, inc.iso_max_jump_pct
    return step_for(ex, athlete), None


def step_for(ex: Optional[LibraryExercise], athlete: Athlete) -> float:
    """The smallest weight jump for an exercise (5 lb dumbbells, one plate on a machine)."""
    if ex is None or ex.step == "dumbbell":
        return athlete.increments.dumbbell
    if ex.step == "machine":
        return athlete.increments.machine
    if ex.step == "cable":
        return athlete.increments.cable
    return 0.0


# App pattern id → library pattern, where the two differ.
APP_PATTERNS = {"overhead_press": "vertical_push", "incline_press": "incline_push"}


def apply_app_rules(athlete: Athlete, rules: Optional[dict], units: Optional[str] = None) -> tuple[Athlete, dict]:
    """Your rules from the app (Settings → Training) laid over athlete.yaml.

    Returns the athlete the coach should use and the sections that differ from the file, in the
    file's own shape (for the agents' prompt). Anything the app didn't send keeps the file's value.
    Limits from the app replace the file's limits, except note-only ones (like knee_test) that the
    app doesn't edit; a note on a limit the app also has is kept.
    """
    base = athlete.model_dump()
    data = athlete.model_dump()
    if units in ("lb", "kg"):
        data["units"] = units
    r = rules if isinstance(rules, dict) else {}

    if isinstance(r.get("limits"), list):
        # The app names a few movement patterns differently from the library.
        file_limits = {x["id"]: x for x in base["injuries_and_limits"]}
        app = []
        for x in r["limits"]:
            if not isinstance(x, dict) or not x.get("id"):
                continue
            name = str(x.get("name") or "").strip()
            summary = str(x.get("summary") or "").strip()
            file_summary = file_limits.get(str(x["id"]), {}).get("summary", "")
            if summary and summary in file_summary:
                text = file_summary  # same words as the file: keep the file's fuller version
            elif name and summary and name.lower() not in summary.lower():
                text = f"{name}: {summary}"
            else:
                text = summary or name or str(x["id"])
            app.append(
                {
                    "id": str(x["id"]),
                    "summary": text,
                    "banned_patterns": list(dict.fromkeys(APP_PATTERNS.get(str(p), str(p)) for p in x.get("banned_patterns") or [])),
                    "banned_exercises": [str(e) for e in x.get("banned_exercises") or []],
                    "rep_caps": [{"match": str(c["match"]), "max": int(c["max"])} for c in x.get("rep_caps") or [] if isinstance(c, dict) and c.get("match") and isinstance(c.get("max"), (int, float))],
                    "note": file_limits.get(str(x["id"]), {}).get("note", ""),
                }
            )
        app_ids = {x["id"] for x in app}
        notes_only = [x for x in base["injuries_and_limits"] if x["id"] not in app_ids and not x["banned_patterns"] and not x["banned_exercises"] and not x.get("rep_caps")]
        data["injuries_and_limits"] = app + notes_only

    if isinstance(r.get("equipment"), list):
        data["equipment"] = [str(e) for e in r["equipment"]]
    for key in ("one_cable_at_a_time", "weights_only"):
        if isinstance(r.get(key), bool):
            data["preferences"][key] = r[key]
    mr = r.get("max_reps")
    if isinstance(mr, (int, float)) and not isinstance(mr, bool) and mr >= 0:
        data["preferences"]["max_reps"] = int(mr)

    steps = r.get("steps") if isinstance(r.get("steps"), dict) else {}
    for key in ("dumbbell", "machine", "cable"):
        v = steps.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            data["increments"][key] = float(v)
    iso = r.get("iso_steps") if isinstance(r.get("iso_steps"), dict) else {}
    for key in ("dumbbell", "cable"):
        v = iso.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            data["increments"][f"iso_{key}"] = float(v)
    a = r.get("assist_step")
    if isinstance(a, (int, float)) and not isinstance(a, bool) and a > 0:
        data["increments"]["assist"] = float(a)
    jump = r.get("max_jump_pct")
    if isinstance(jump, (int, float)) and not isinstance(jump, bool) and 0 < jump <= 1:
        data["increments"]["max_jump_pct"] = float(jump)

    days = r.get("days")
    if isinstance(days, list) and days and all(isinstance(d, int) and 1 <= d <= 7 for d in days):
        data["schedule"]["days"] = sorted(set(days))
        data["schedule"]["days_per_week"] = len(data["schedule"]["days"])
    mins = r.get("session_minutes")
    if isinstance(mins, dict) and isinstance(mins.get("min"), int) and isinstance(mins.get("max"), int) and 0 < mins["min"] <= mins["max"]:
        data["schedule"]["session_minutes"] = {"min": mins["min"], "max": mins["max"]}
    n = r.get("exercises_per_workout")
    if isinstance(n, int) and not isinstance(n, bool) and n > 0:
        old = data["schedule"]["exercises_per_workout"]
        if old["target"] != n:
            data["schedule"]["exercises_per_workout"] = {"target": n, "min": max(1, n - 1), "max": n + 1}

    effective = Athlete.model_validate(data)
    changed = {k: data[k] for k in data if data[k] != base[k]}
    return effective, changed
