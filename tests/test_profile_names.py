"""Names without the old "(knee test)" tag, and timed holds outside the cap."""

from coach.profile import (
    apply_app_rules,
    is_timed_hold,
    load_athlete,
    load_library,
    rep_cap,
)

NEW_EXERCISES = [
    "Seated DB Shrug",
    "Chest-Supported DB Shrug",
    "Seated DB Wrist Curl",
    "DB Reverse Curl",
    "Seated Dumbbell Hold",
    "Assisted Dead Hang",
    "Glute Bridge",
    "Reverse Crunch",
]


def test_trial_exercises_are_found_with_or_without_the_old_tag():
    library = load_library()
    names = [
        "Sit-Up Bench Crunch",
        "Sit-Up Bench Crunch (knee test)",
        "Hammer Strength Glute/Ham Hip Extension (knee test)",
        "Reverse Crunch",
    ]
    found = [library.find(name) for name in names]
    assert all(ex is not None and ex.trial for ex in found)
    assert library.find("Glute Bridge").trial is False


def test_the_six_day_plans_new_exercises_are_listed_and_allowed():
    library, athlete = load_library(), load_athlete()
    found = [library.find(name) for name in NEW_EXERCISES]
    assert all(ex is not None for ex in found)
    assert all(ex.knee != "loads" for ex in found)
    assert not {ex.pattern for ex in found} & athlete.banned_patterns
    needed = {item for ex in found for item in ex.equipment}
    assert needed <= set(athlete.equipment)


def test_timed_holds_count_seconds_so_the_general_rep_cap_skips_them():
    athlete, _ = apply_app_rules(load_athlete(), {"max_reps": 12})
    timed = ["Assisted Dead Hang", "Seated Dumbbell Hold", "Plank"]
    counted = ["Seated DB Shrug", "Hanging Leg Raise"]
    assert all(is_timed_hold(name) for name in timed)
    assert not any(is_timed_hold(name) for name in counted)
    assert [rep_cap(name, athlete) for name in timed[:2]] == [None, None]
    assert rep_cap("Seated DB Shrug", athlete) == 12
