"""The eval scenarios: a snapshot (made by the app's own builder, see fixtures/generate.ts) and what a
good answer must and must not do. Run them with `coach evals`; export them for LangSmith with
`python -m evals.scenarios --export`.

Expectations are deliberately loose about *which* good answer, strict about bad ones: a range of
acceptable change levels, exercises that must (or must never) be touched in certain ways.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
DATASETS = Path(__file__).parent / "datasets"


@dataclass
class Expect:
    levels: set[int] = field(default_factory=lambda: set(range(7)))
    recommendation: str | None = None
    # Exercise → change types allowed; the exercise must be changed with one of them.
    must_touch: dict[str, set[str]] = field(default_factory=dict)
    # Exercise → change types it must never get.
    forbid_types_on: dict[str, set[str]] = field(default_factory=dict)
    # No new exercise whose name contains any of these.
    forbid_names: list[str] = field(default_factory=list)
    # Exercises that must never get more weight, sets or reps.
    forbid_increase_on: set[str] = field(default_factory=set)
    why: str = ""


@dataclass
class Scenario:
    name: str
    expect: Expect

    def snapshot(self) -> dict:
        return json.loads((FIXTURES / f"{self.name}.json").read_text())


BENCH = "Flat DB Bench Press"
LAT = "Lat Pulldown"
RAISE = "Seated Lateral Raise"
PRESS = "Seated DB Shoulder Press"
CRUNCH = "Sit-Up Bench Crunch (knee test)"

SCENARIOS: list[Scenario] = [
    Scenario("ready_to_progress", Expect(levels={1, 2}, must_touch={BENCH: {"load", "reps"}}, why="Bench at 12, 12, 12 rated 7 two workouts running: reps to spare, move it up.")),
    Scenario("missed_sessions", Expect(levels={0, 1}, why="Three workouts a week lately against a usual five: keep it simple, don't add change.")),
    Scenario("pain_note", Expect(levels={4}, must_touch={CRUNCH: {"remove", "swap"}}, forbid_types_on={CRUNCH: {"load", "reps", "sets"}}, why="A knee-test exercise hurt twice: remove it.")),
    Scenario("stall", Expect(levels={0, 1, 3, 4}, forbid_types_on={LAT: {"load"}}, why="Lat pulldown flat for weeks after a weight increase: reps, a set or a swap; not more weight.")),
    Scenario("recent_program_change", Expect(levels={0, 1, 2, 3, 4}, why="The program changed two weeks ago: no new program now.")),
    Scenario("small_dumbbell", Expect(levels={0, 1, 2, 3}, forbid_types_on={RAISE: {"load"}}, why="12.5 → 17.5 lb is a 40% jump: progress raises with reps or a set.")),
    Scenario("comment_conflict", Expect(levels={0, 1, 2, 3, 4}, forbid_names=["squat", "lunge", "leg press", "deadlift"], why="A note asks for squats; the knee rule wins.")),
    Scenario("block_end_stalled", Expect(levels={3, 4, 5, 6}, why="Twelve weeks in, at a block's end, most lifts flat for weeks: a real change is due.")),
    Scenario("too_little_data", Expect(levels={0}, recommendation="none", why="One week of data: too early to recommend anything.")),
    Scenario("cutting_holding", Expect(levels={0, 1, 2}, why="Losing 1.5 lb a week with lifts holding: that's a win; keep going.")),
    Scenario("all_progressing", Expect(levels={0, 1, 2}, why="Everything moving mid-block: hold, or the smallest step.")),
    Scenario("last_not_applied", Expect(levels={0, 1, 2}, why="Last week's bench increase wasn't applied: don't escalate.")),
    Scenario("fatigue_deload", Expect(levels={5}, why="Six lifts rated harder at the same weights, reps slipping, whole workouts at 9, a tired note: a lighter week.")),
    Scenario("too_heavy", Expect(levels={1, 2, 3, 4}, must_touch={PRESS: {"load", "reps", "sets"}}, forbid_increase_on={PRESS}, why="Shoulder press reps falling three workouts running at a 9–10: lighter, not heavier.")),
]


def by_name(name: str) -> Scenario:
    return next(s for s in SCENARIOS if s.name == name)


def export() -> Path:
    """Write the dataset LangSmith reads: inputs = the snapshot, reference outputs = the expectations."""
    DATASETS.mkdir(exist_ok=True)
    rows = []
    for s in SCENARIOS:
        e = asdict(s.expect)
        e["levels"] = sorted(e["levels"])
        e["must_touch"] = {k: sorted(v) for k, v in e["must_touch"].items()}
        e["forbid_types_on"] = {k: sorted(v) for k, v in e["forbid_types_on"].items()}
        e["forbid_increase_on"] = sorted(e["forbid_increase_on"])
        rows.append({"name": s.name, "inputs": {"scenario": s.name}, "outputs": e})
    out = DATASETS / "scenarios.json"
    out.write_text(json.dumps(rows, indent=2))
    return out


if __name__ == "__main__":
    if "--export" in sys.argv:
        print(export())
