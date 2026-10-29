"""What the agents produce, and the decision that goes back to the app.

`Decision` and `Change` match the `Decision` / `DecisionChange` types in the app's
`supabase/functions/_shared/workout_history.ts`; the Edge Function checks them before saving.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ChangeType = Literal["reps", "load", "sets", "swap", "add", "remove", "deload", "program", "rest", "other"]

# The change ladder: the size of a change, smallest first. The governor and the critic reason in these.
LEVELS: dict[int, str] = {
    0: "Hold: no change",
    1: "Reps: +1–2 within the range",
    2: "Load: the smallest weight step",
    3: "Sets: ±1 set",
    4: "Swap one exercise",
    5: "Lighter (deload) week",
    6: "New program",
}

# The level a single change implies on its own.
TYPE_LEVEL: dict[str, int] = {"reps": 1, "load": 2, "sets": 3, "rest": 1, "other": 1, "swap": 4, "add": 4, "remove": 4, "deload": 5, "program": 6}


class ExerciseTarget(BaseModel):
    """Only the fields that change. `name` is set for a swap or an added exercise."""

    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = None
    sets: Optional[int] = None
    reps_min: Optional[int] = None
    reps_max: Optional[int] = None
    weight: Optional[float] = None
    rest: Optional[str] = None
    note: Optional[str] = None


class Change(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    workout: str
    action_id: Optional[str] = None
    type: ChangeType
    exercise: str
    from_: Optional[ExerciseTarget] = Field(default=None, alias="from")
    to: Optional[ExerciseTarget] = None
    reason: str

    @property
    def level(self) -> int:
        return TYPE_LEVEL[self.type]


class Option(BaseModel):
    id: str
    label: str
    change_level: int = Field(ge=0, le=6)
    changes: list[Change] = []
    expected_benefit: str = ""
    costs: str = ""
    rationale: list[str] = []

    @field_validator("change_level")
    @classmethod
    def _level(cls, v: int) -> int:
        return int(v)


class Options(BaseModel):
    options: list[Option]
    recommended_option_id: str


class ExerciseRead(BaseModel):
    exercise: str
    verdict: Literal["ready_to_progress", "progressing", "holding", "stalled", "regressing", "pain", "too_early", "not_done"]
    evidence: list[str] = []
    note: str = ""


class Assessment(BaseModel):
    summary: str
    attendance: str
    recovery: str
    program_fit: str
    program_due_for_change: bool = False
    program_change_reason: str = ""
    exercises: list[ExerciseRead]
    flags: list[str] = []


class CriticVerdict(BaseModel):
    chosen_option_id: str
    verdict: Literal["accept", "downgrade", "revise"]
    # Changes from the chosen option to drop (by exercise name) when downgrading.
    drop_exercises: list[str] = []
    reasons: list[str] = []
    would_change_mind: list[str] = []
    revise_instructions: Optional[str] = None


class Decision(BaseModel):
    """What the app stores and the report shows. recommendation 'none' means the coach couldn't decide this week."""

    model_config = ConfigDict(populate_by_name=True)
    recommendation: Literal["hold", "change", "none"]
    change_level: int = Field(ge=0, le=6)
    summary: str
    changes: list[Change] = []
    rationale: list[str] = []
    would_change_mind: list[str] = []
    block: Optional[dict] = None

    def to_payload(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True)
