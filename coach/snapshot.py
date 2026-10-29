"""The workout history snapshot, schema 1: the agent's only input from the app.

Mirrors `supabase/functions/_shared/workout_history.ts` in the six-month-plan repo. Unknown fields are
kept (extra="allow") so a newer app doesn't break an older agent, but a different schema_version is
refused: the app bumps it only for breaking changes.
"""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1"


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow")


class Exercise(_Model):
    name: str
    sets: int
    reps_min: int
    reps_max: int
    per_side: Optional[bool] = None
    weight: Optional[float] = None
    weight_note: Optional[str] = ""
    rest: Optional[str] = ""
    note: Optional[str] = ""


class Meta(_Model):
    schema_version: str
    as_of: str
    months: int
    from_: str = Field(alias="from")
    units: str
    timezone: str
    fingerprint: str


class PlanVersion(_Model):
    effective_on: str
    source: str
    reason: str = ""
    exercises: list[Exercise]


class Workout(_Model):
    action_id: str
    title: str
    days: list[int]
    planned_minutes: int
    estimated_minutes: int
    details: str = ""
    exercises: list[Exercise]
    current_since: Optional[str] = None
    versions: list[PlanVersion] = []


class Program(_Model):
    workouts: list[Workout]
    workouts_per_week: int
    last_structural_change_on: Optional[str] = None
    program_age_weeks: Optional[int] = None
    last_target_change_on: Optional[str] = None


class SetRow(_Model):
    exercise: str
    set_no: int
    weight: Optional[float] = None
    reps: Optional[int] = None
    done: bool
    rir: Optional[int] = None
    pain: bool = False


class Session(_Model):
    date: str
    week_start: str
    action_id: Optional[str] = None
    workout: str
    status: str
    minutes: Optional[int] = None
    note: str = ""
    sets: list[SetRow] = []


class ExerciseWeek(_Model):
    week_start: str
    exercise: str
    sets_done: int
    best_weight: Optional[float] = None
    best_reps: Optional[int] = None
    e1rm: Optional[float] = None
    volume: float
    avg_rir: Optional[float] = None
    pain: bool = False


class Planned(_Model):
    sets: int
    reps_min: int
    reps_max: int
    weight: Optional[float] = None


class ExerciseMetrics(_Model):
    exercise: str
    workouts: list[str] = []
    planned: Optional[Planned] = None
    sessions: int
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    last_weight: Optional[float] = None
    e1rm_now: Optional[float] = None
    e1rm_3w_ago: Optional[float] = None
    e1rm_trend_pct: Optional[float] = None
    weeks_since_gain: Optional[int] = None
    stalled: bool = False
    top_of_range_streak: int = 0
    avg_rir_2w: Optional[float] = None
    pain_flags_4w: int = 0
    next_step_pct: Optional[float] = None


class WeeklySets(_Model):
    week_start: str
    sets: int


class Metrics(_Model):
    exercises: list[ExerciseMetrics]
    attendance_4w: Optional[float] = None
    attendance_8w: Optional[float] = None
    workouts_done_4w: int = 0
    workouts_planned_4w: int = 0
    set_completion_4w: Optional[float] = None
    avg_session_minutes_4w: Optional[int] = None
    weekly_sets: list[WeeklySets] = []


class Comment(_Model):
    date: Optional[str] = None
    source: Literal["plan_note", "details", "session_note"]
    workout: str
    exercise: Optional[str] = None
    text: str


class Reading(_Model):
    date: str
    value: float


class WeeklyWeight(_Model):
    week_start: str
    avg: float


class BodyweightShared(_Model):
    shared: Literal[True]
    unit: str
    latest: Optional[Reading] = None
    weekly: list[WeeklyWeight] = []
    trend_per_week: Optional[float] = None


class BodyweightHidden(_Model):
    shared: Literal[False]


class PastChange(_Model):
    workout: str
    action_id: Optional[str] = None
    type: str
    exercise: str
    from_: Optional[dict] = Field(default=None, alias="from")
    to: Optional[dict] = None
    reason: str = ""


class PastDecision(_Model):
    id: str
    as_of: str
    recommendation: str
    change_level: int
    summary: str = ""
    changes: list[PastChange] = []
    user_status: Optional[str] = None
    inferred_status: str
    user_note: str = ""


class SinceLast(_Model):
    last_report_as_of: Optional[str] = None
    sessions: list[str] = []
    sets: int = 0
    plan_changes: list[str] = []
    comments: int = 0


class Snapshot(_Model):
    meta: Meta
    program: Program
    sessions: list[Session]
    history: list[ExerciseWeek]
    metrics: Metrics
    comments: list[Comment] = []
    bodyweight: Union[BodyweightShared, BodyweightHidden]
    decisions: list[PastDecision] = []
    since_last: Optional[SinceLast] = None

    def exercise(self, name: str) -> Optional[ExerciseMetrics]:
        key = name.strip().lower()
        return next((e for e in self.metrics.exercises if e.exercise.strip().lower() == key), None)

    def workout(self, title_or_id: str) -> Optional[Workout]:
        key = title_or_id.strip().lower()
        return next((w for w in self.program.workouts if w.action_id == title_or_id or w.title.strip().lower() == key), None)


class SnapshotError(ValueError):
    """The snapshot can't be used: wrong schema, or it fails its own arithmetic."""


def parse_snapshot(data: dict) -> Snapshot:
    version = str((data.get("meta") or {}).get("schema_version", ""))
    if version != SCHEMA_VERSION:
        raise SnapshotError(f"Snapshot schema {version!r}; this agent reads schema {SCHEMA_VERSION!r}. Update coach/snapshot.py.")
    return Snapshot.model_validate(data)
