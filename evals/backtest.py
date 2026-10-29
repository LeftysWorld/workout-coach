"""Replay past Fridays: what would the coach have said, what would the simple rule have said, and
what actually happened next?

    coach backtest --from 2026-11-06 --to 2027-01-29

For each Friday it asks the app for the snapshot *as of that day* (the app can rebuild any past
date), runs the pipeline in dry-run mode, and compares with the baseline: double progression, the rule
the app already uses (top of the range on every set → one step up), applied to every exercise.

Then it looks two weeks later and scores what happened (coach/score.py week_score), and checks:
- safety: no recommendation ever pushed an exercise with a pain flag
- churn: how many changes per week each policy asks for (fewer is better at equal outcomes)
- agreement: how often the coach and the rule recommend the same thing for an exercise
- follow-through: of the weeks after a change, how many scored at least as well as the week before

Ship a new prompt, skill or model only if it does at least as well as the rule on your own history.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from coach.client import AppClient
from coach.flow import Context
from coach.profile import load_athlete, load_library, step_for
from coach.runner import run_plain
from coach.score import REWARD_VERSION, week_score
from coach.snapshot import Snapshot, parse_snapshot

OUT = Path("out")


def fridays(start: str, end: str) -> list[str]:
    d = date.fromisoformat(start)
    d += timedelta(days=(4 - d.weekday()) % 7)
    out = []
    while d <= date.fromisoformat(end):
        out.append(d.isoformat())
        d += timedelta(days=7)
    return out


def baseline(s: Snapshot) -> dict[str, str]:
    """Double progression: exercise → 'load' when every set hit the top of the range last time and the step is small enough; else 'hold'."""
    athlete, library = load_athlete(), load_library()
    out = {}
    for m in s.metrics.exercises:
        if not m.planned:
            continue
        step = step_for(library.find(m.exercise), athlete)
        small = bool(step and m.last_weight and step / m.last_weight <= athlete.increments.max_jump_pct)
        out[m.exercise] = "load" if m.top_of_range_streak >= 1 and small and m.pain_flags_4w == 0 else ("reps" if m.top_of_range_streak >= 1 else "hold")
    return out


def main(start: str, end: str, scripted: bool = False, months: int = 6) -> int:
    client = AppClient()
    if scripted:
        from .scripted import scripted_llm as make
    else:
        from coach.llm import AnthropicLLM as make  # type: ignore[assignment]
    rows = []
    for friday in fridays(start, end):
        raw = client.history(friday, months)
        snap = parse_snapshot(raw)
        state = run_plain(Context(llm=make(), athlete=load_athlete(), library=load_library(), snapshot_json=raw))
        d = state["decision"]
        coach = {c.exercise: c.type for c in d.changes}
        base = baseline(snap)
        later_day = (date.fromisoformat(friday) + timedelta(days=14)).isoformat()
        later = parse_snapshot(client.history(later_day, months)) if later_day <= date.today().isoformat() else None
        pain = {m.exercise for m in snap.metrics.exercises if m.pain_flags_4w > 0}
        rows.append(
            {
                "as_of": friday,
                "coach": {"recommendation": d.recommendation, "level": d.change_level, "changes": coach},
                "baseline": {k: v for k, v in base.items() if v != "hold"},
                "agreement": round(sum(1 for k, v in base.items() if coach.get(k, "hold") == v) / len(base), 3) if base else None,
                "unsafe": sorted(k for k, v in coach.items() if k in pain and v in {"load", "reps", "sets"}),
                "score_now": week_score(snap)["score"],
                "score_2w_later": week_score(later)["score"] if later else None,
            }
        )
        print(f"{friday}: coach {d.recommendation} L{d.change_level} ({len(coach)} changes) · rule {len(rows[-1]['baseline'])} · agreement {rows[-1]['agreement']} · score {rows[-1]['score_now']} → {rows[-1]['score_2w_later']}")
    after_change = [r for r in rows if r["coach"]["changes"] and r["score_2w_later"] is not None]
    summary = {
        "reward": REWARD_VERSION,
        "weeks": len(rows),
        "unsafe_weeks": sum(1 for r in rows if r["unsafe"]),
        "coach_changes_per_week": round(sum(len(r["coach"]["changes"]) for r in rows) / max(1, len(rows)), 2),
        "rule_changes_per_week": round(sum(len(r["baseline"]) for r in rows) / max(1, len(rows)), 2),
        "agreement": round(sum(r["agreement"] or 0 for r in rows) / max(1, len(rows)), 3),
        "follow_through": round(sum(1 for r in after_change if r["score_2w_later"] >= r["score_now"]) / len(after_change), 3) if after_change else None,
    }
    print(json.dumps(summary, indent=2))
    OUT.mkdir(exist_ok=True)
    (OUT / f"backtest-{start}-{end}.json").write_text(json.dumps({"summary": summary, "weeks": rows}, indent=2))
    return 1 if summary["unsafe_weeks"] else 0
