"""Your rules from the app's Settings → Training, laid over profile/athlete.yaml."""

import copy

import yaml

from coach.profile import apply_app_rules, load_athlete
from coach.prompts import system_prompt

# What the app saves when you open Settings → Training and change nothing (DEFAULT_TRAINING_RULES).
APP_DEFAULTS = {
    "limits": [
        {
            "id": "knee",
            "name": "Knee",
            "summary": "No lower-body training. Anything that loads the knee is out.",
            "banned_patterns": ["squat", "lunge", "leg_press", "leg_extension", "leg_curl", "step_up", "jump", "deadlift", "kettlebell_swing"],
            "banned_exercises": ["Weighted crunch", "Seated kettlebell twist", "Hollow-body hold", "Dead bug"],
        }
    ],
    "equipment": ["dumbbells", "adjustable_bench", "incline_bench", "sit_up_bench", "single_cable", "lat_pulldown", "seated_cable_row", "chest_press_machine", "hammer_strength_back_extension", "hammer_strength_glute_ham", "rear_delt_machine"],
    "one_cable_at_a_time": True,
    "weights_only": True,
    "steps": {"dumbbell": 5, "machine": 5, "cable": 5},
    "max_jump_pct": 0.1,
    "days": [1, 2, 3, 4, 5],
    "session_minutes": {"min": 35, "max": 45},
    "exercises_per_workout": 5,
}


def test_nothing_saved_keeps_the_file():
    a = load_athlete()
    eff, changed = apply_app_rules(a, None, "lb")
    assert changed == {}
    assert eff == a


def test_the_apps_defaults_match_the_file():
    eff, changed = apply_app_rules(load_athlete(), APP_DEFAULTS, "lb")
    assert changed == {}, changed
    # The note-only knee_test limit and the knee note survive.
    ids = [x.id for x in eff.injuries_and_limits]
    assert ids == ["knee", "knee_test"]
    assert eff.injuries_and_limits[0].note


def test_app_changes_win():
    rules = copy.deepcopy(APP_DEFAULTS)
    rules["equipment"].append("barbell")
    rules["steps"]["dumbbell"] = 2.5
    rules["days"] = [1, 3, 5]
    rules["exercises_per_workout"] = 6
    rules["limits"][0]["banned_exercises"].append("Plank")
    rules["limits"].append({"id": "limit-1", "name": "Left shoulder", "summary": "No overhead pressing", "banned_patterns": ["overhead_press"], "banned_exercises": []})
    eff, changed = apply_app_rules(load_athlete(), rules, "lb")
    assert "barbell" in eff.equipment
    assert eff.increments.dumbbell == 2.5
    assert eff.schedule.days == [1, 3, 5] and eff.schedule.days_per_week == 3
    assert eff.schedule.exercises_per_workout.target == 6
    assert "plank" in eff.banned_exercises
    assert "overhead_press" in eff.banned_patterns
    assert eff.injuries_and_limits[1].summary == "Left shoulder: No overhead pressing"
    assert set(changed) == {"equipment", "increments", "schedule", "injuries_and_limits"}


def test_removing_the_knee_limit_in_the_app_removes_it():
    rules = copy.deepcopy(APP_DEFAULTS)
    rules["limits"] = []
    eff, _ = apply_app_rules(load_athlete(), rules, "lb")
    assert "squat" not in eff.banned_patterns
    assert [x.id for x in eff.injuries_and_limits] == ["knee_test"]


def test_bad_values_are_ignored():
    rules = {"steps": {"dumbbell": -5, "cable": "five"}, "days": [0, 9], "max_jump_pct": 3, "session_minutes": {"min": 50, "max": 40}, "exercises_per_workout": True}
    eff, changed = apply_app_rules(load_athlete(), rules, None)
    assert changed == {}
    assert eff == load_athlete()


def test_units_follow_the_app():
    eff, changed = apply_app_rules(load_athlete(), None, "kg")
    assert eff.units == "kg" and changed == {"units": "kg"}


def test_prompts_show_settings_changes_only_where_the_agent_reads_them():
    _, changed = apply_app_rules(load_athlete(), {"equipment": ["dumbbells"], "limits": []}, "lb")
    updates = yaml.safe_dump(changed, sort_keys=False)
    planner = system_prompt("planner", updates)
    analyst = system_prompt("analyst", updates)
    assert "Updated in the app's Settings" in planner and "equipment" in planner.split("Updated in the app's Settings")[1]
    # The analyst reads only goals and limits: it sees the limit change, not the equipment list.
    tail = analyst.split("Updated in the app's Settings")[1]
    assert "injuries_and_limits" in tail and "equipment" not in tail
    assert "Updated in the app's Settings" not in system_prompt("planner")
