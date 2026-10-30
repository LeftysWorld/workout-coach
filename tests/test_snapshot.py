import copy
import json

import pytest

from coach import metrics
from coach.snapshot import SnapshotError, parse_snapshot
from tests.conftest import FIXTURES


@pytest.mark.parametrize("path", sorted(p.stem for p in FIXTURES.glob("*.json")))
def test_every_fixture_parses_and_passes_its_own_arithmetic(raw, path):
    s = parse_snapshot(raw(path))
    metrics.check_contract(s)


def test_a_different_schema_is_refused(raw):
    data = raw()
    data["meta"]["schema_version"] = "1"
    with pytest.raises(SnapshotError, match="schema"):
        parse_snapshot(data)


def test_tampered_numbers_stop_the_run(raw):
    data = copy.deepcopy(raw())
    data["metrics"]["exercises"][0]["e1rm_now"] = 999
    with pytest.raises(SnapshotError, match="arithmetic"):
        metrics.check_contract(parse_snapshot(data))


def test_epley_matches_the_app():
    assert metrics.e1rm(100, 10) == 133.3
    assert metrics.e1rm(None, 10) is None
    assert metrics.e1rm(100, 20) is None


def test_facts_mark_big_jumps_and_the_block(raw, athlete, library):
    s = parse_snapshot(raw("small_dumbbell"))
    f = metrics.build_facts(s, athlete, library)
    raise_ = next(e for e in f["exercises"] if e["exercise"] == "Seated Lateral Raise")
    assert raise_["jump_too_big"] is True and raise_["step_pct"] == 0.4
    assert f["block"]["block_number"] == 2 and f["block"]["week_in_block"] == 2
    end = metrics.build_facts(parse_snapshot(raw("block_end_stalled")), athlete, library)["block"]
    assert end["at_block_end"] is True


def test_too_little_data_is_caught(raw):
    ok, why = metrics.enough_data(parse_snapshot(raw("too_little_data")))
    assert not ok and "two weeks" in why


def test_the_analyst_never_sees_the_plan(raw, athlete, library):
    f = metrics.build_facts(parse_snapshot(raw()), athlete, library)
    view = metrics.analyst_view(f)
    assert "workouts" in f and "plan_notes" in f
    assert "workouts" not in view and "plan_notes" not in view
    text = json.dumps(view)
    for gone in ("reps_min", "reps_max", "planned", "attendance", "top_of_range", '"details"', "plan_note"):
        assert gone not in text, gone


def test_signals_read_what_was_done(raw, athlete, library):
    def ex(name, scenario):
        f = metrics.build_facts(parse_snapshot(raw(scenario)), athlete, library)
        return next(e for e in f["exercises"] if e["exercise"] == name), f["program_signals"]

    bench, _ = ex("Flat DB Bench Press", "ready_to_progress")
    assert bench["ready_to_add_weight"] and not bench["too_heavy"]
    press, ps = ex("Seated DB Shoulder Press", "too_heavy")
    assert press["too_heavy"] and not press["ready_to_add_weight"]
    assert not ps["deload_suggested"]
    lat, _ = ex("Lat Pulldown", "stall")
    assert lat["stalled"] and not lat["ready_to_add_weight"]
    _, tired = ex("Flat DB Bench Press", "fatigue_deload")
    assert tired["deload_suggested"] and len(tired["exercises_getting_harder"]) >= 3
    assert "whole workouts rated harder than usual" in tired["deload_signals"]
    _, fewer = ex("Flat DB Bench Press", "missed_sessions")
    assert fewer["consistency_ratio"] < 0.75 and not fewer["deload_suggested"]


def test_body_measurements_come_through_while_cutting(raw, athlete, library):
    f = metrics.build_facts(parse_snapshot(raw("cutting_holding")), athlete, library)
    names = {b["name"]: b for b in f["body_measurements"]}
    assert set(names) == {"Waist", "Chest", "Right arm", "Left arm", "Shoulders"}
    assert names["Waist"]["change_4w"] == -1 and names["Right arm"]["change_4w"] == 0
    assert 0.5 < f["program_signals"]["bodyweight_loss_pct_per_week"] < 1.0
