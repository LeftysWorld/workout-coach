"""Your rules (profile/athlete.yaml) and the exercises the coach may use (profile/exercise_library.yaml)."""

from __future__ import annotations

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
    note: str = ""


class Preferences(BaseModel):
    weights_only: bool = True
    prefer_dumbbells: bool = True
    barbells_allowed: bool = False
    one_cable_at_a_time: bool = True
    keep_duration_steady: bool = True


class Increments(BaseModel):
    dumbbell: float = 5
    machine: float = 5
    cable: float = 5
    max_jump_pct: float = 0.10


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


def step_for(ex: Optional[LibraryExercise], athlete: Athlete) -> float:
    """The smallest weight jump for an exercise (5 lb dumbbells, one plate on a machine)."""
    if ex is None or ex.step == "dumbbell":
        return athlete.increments.dumbbell
    if ex.step == "machine":
        return athlete.increments.machine
    if ex.step == "cable":
        return athlete.increments.cable
    return 0.0


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
                    "banned_patterns": [str(p) for p in x.get("banned_patterns") or []],
                    "banned_exercises": [str(e) for e in x.get("banned_exercises") or []],
                    "note": file_limits.get(str(x["id"]), {}).get("note", ""),
                }
            )
        app_ids = {x["id"] for x in app}
        notes_only = [x for x in base["injuries_and_limits"] if x["id"] not in app_ids and not x["banned_patterns"] and not x["banned_exercises"]]
        data["injuries_and_limits"] = app + notes_only

    if isinstance(r.get("equipment"), list):
        data["equipment"] = [str(e) for e in r["equipment"]]
    for key in ("one_cable_at_a_time", "weights_only"):
        if isinstance(r.get(key), bool):
            data["preferences"][key] = r[key]

    steps = r.get("steps") if isinstance(r.get("steps"), dict) else {}
    for key in ("dumbbell", "machine", "cable"):
        v = steps.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            data["increments"][key] = float(v)
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
