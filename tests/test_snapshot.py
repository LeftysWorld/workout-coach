import copy

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
    data["meta"]["schema_version"] = "2"
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
