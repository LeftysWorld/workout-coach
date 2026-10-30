from coach import metrics
from coach.decision import Change, ExerciseTarget, Option
from coach.governor import apply_changes, check
from coach.snapshot import parse_snapshot


def ctx(raw, athlete, library, name="ready_to_progress"):
    s = parse_snapshot(raw(name))
    return s, metrics.build_facts(s, athlete, library)["block"]


def opt(level, *changes):
    return Option(id="x", label="x", change_level=level, changes=list(changes))


def ch(workout, exercise, type_, frm=None, to=None):
    return Change(workout=workout, exercise=exercise, type=type_, **{"from": ExerciseTarget(**(frm or {}))}, to=ExerciseTarget(**(to or {})) if to is not None else None, reason="test")


MON = "Mon: Chest + Back"
WED = "Wed: Back + Core"


def codes(v):
    return {x.code for x in v}


def test_a_small_valid_change_passes(raw, athlete, library):
    s, block = ctx(raw, athlete, library)
    assert check(opt(2, ch(MON, "Flat DB Bench Press", "load", {"weight": 50}, {"weight": 55})), s, athlete, library, block) == []


def test_hold_cannot_carry_changes_and_levels_must_match(raw, athlete, library):
    s, block = ctx(raw, athlete, library)
    assert "hold_with_changes" in codes(check(opt(0, ch(MON, "Flat DB Bench Press", "reps", {"reps_max": 12}, {"reps_max": 13})), s, athlete, library, block))
    assert "level_too_low" in codes(check(opt(1, ch(MON, "Flat DB Bench Press", "load", {"weight": 50}, {"weight": 55})), s, athlete, library, block))


def test_weight_jumps_over_the_limit_are_refused(raw, athlete, library):
    s, block = ctx(raw, athlete, library, "small_dumbbell")
    v = codes(check(opt(2, ch(MON, "Seated Lateral Raise", "load", {"weight": 12.5}, {"weight": 17.5})), s, athlete, library, block))
    assert "load_jump_pct" in v
    v = codes(check(opt(2, ch(MON, "Flat DB Bench Press", "load", {"weight": 50}, {"weight": 60})), s, athlete, library, block))
    assert "load_jump_too_big" in v


def test_knee_banned_two_cable_and_unknown_exercises_are_refused(raw, athlete, library):
    s, block = ctx(raw, athlete, library)
    assert "knee" in codes(check(opt(4, ch(MON, "Seated Lateral Raise", "swap", {"name": "Seated Lateral Raise"}, {"name": "Goblet Squat"})), s, athlete, library, block))
    assert "two_cables" in codes(check(opt(4, ch(MON, "Seated Lateral Raise", "swap", {}, {"name": "Cable Fly (two cables)"})), s, athlete, library, block))
    assert "not_in_library" in codes(check(opt(4, ch(MON, "Seated Lateral Raise", "swap", {}, {"name": "Jump Squats"})), s, athlete, library, block))
    assert "unknown_exercise" in codes(check(opt(1, ch(MON, "Nonexistent", "reps", {}, {"reps_max": 9})), s, athlete, library, block))


def test_pain_is_never_pushed_but_can_be_removed(raw, athlete, library):
    s, block = ctx(raw, athlete, library, "pain_note")
    crunch = "Sit-Up Bench Crunch (knee test)"
    assert "pain_progressed" in codes(check(opt(3, ch(WED, crunch, "sets", {"sets": 3}, {"sets": 4})), s, athlete, library, block))
    assert check(opt(4, ch(WED, crunch, "remove", {"name": crunch}, {})), s, athlete, library, block) == []


def test_one_structural_change_a_week_mid_block(raw, athlete, library):
    s, block = ctx(raw, athlete, library)
    two = opt(4, ch(MON, "Seated Lateral Raise", "swap", {}, {"name": "Cable Lateral Raise"}), ch(MON, "Lat Pulldown", "swap", {}, {"name": "Wide-Grip Lat Pulldown"}))
    assert "too_many_swaps" in codes(check(two, s, athlete, library, block))


def test_change_and_volume_limits(raw, athlete, library):
    s, block = ctx(raw, athlete, library, "block_end_stalled")
    many = [ch(w.title, e.name, "sets", {"sets": e.sets}, {"sets": e.sets + 1}) for w in s.program.workouts for e in w.exercises if e.sets < 5][:5]
    v = codes(check(opt(3, *many), s, athlete, library, block))
    assert {"too_many_changes", "too_much_volume"} <= v


def test_a_new_program_needs_time_on_the_old_one(raw, athlete, library):
    s, block = ctx(raw, athlete, library, "recent_program_change")
    v = codes(check(opt(6, ch(MON, "Lat Pulldown", "swap", {}, {"name": "Wide-Grip Lat Pulldown"})), s, athlete, library, block))
    assert "program_too_soon" in v
    s2, block2 = ctx(raw, athlete, library, "block_end_stalled")
    assert "program_too_soon" not in codes(check(opt(6, ch(MON, "Lat Pulldown", "swap", {}, {"name": "Wide-Grip Lat Pulldown"})), s2, athlete, library, block2))


def test_apply_changes_builds_the_next_plan(raw, athlete, library):
    s, _ = ctx(raw, athlete, library)
    plans = apply_changes(s, [ch(MON, "Lat Pulldown", "swap", {}, {"name": "Wide-Grip Lat Pulldown", "reps_min": 10}), ch(MON, "Flat DB Bench Press", "load", {"weight": 50}, {"weight": 55})])
    names = [e["name"] for e in plans[MON]]
    assert "Wide-Grip Lat Pulldown" in names and "Lat Pulldown" not in names
    assert next(e for e in plans[MON] if e["name"] == "Flat DB Bench Press")["weight"] == 55


def test_no_more_weight_on_a_lift_that_is_too_heavy_or_was_all_out(raw, athlete, library):
    s, block = ctx(raw, athlete, library, "too_heavy")
    tue = "Tue: Shoulders + Arms"
    up = check(opt(2, ch(tue, "Seated DB Shoulder Press", "load", {"weight": 35}, {"weight": 40})), s, athlete, library, block)
    assert codes(up) & {"allout_load", "too_heavy_load"}
    down = check(opt(2, ch(tue, "Seated DB Shoulder Press", "load", {"weight": 35}, {"weight": 30})), s, athlete, library, block)
    assert not codes(down) & {"allout_load", "too_heavy_load"}


def test_a_lighter_week_passes_mid_block(raw, athlete, library):
    s, block = ctx(raw, athlete, library, "fatigue_deload")
    assert not block["at_block_end"]
    lighter = [ch(w.title, e.name, "deload", {"sets": e.sets}, {"sets": e.sets - 1}) for w in s.program.workouts for e in w.exercises if e.sets > 1]
    assert check(opt(5, *lighter), s, athlete, library, block) == []
