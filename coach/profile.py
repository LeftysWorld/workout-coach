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
