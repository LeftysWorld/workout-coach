"""Exercise classes and load steps: the same rules as the app's next-session targets (packages/core/src/progression.ts)."""

from coach.profile import exercise_class, load_rule


def test_classes_match_the_app():
    assert exercise_class("Assisted Pull-Up") == "assisted"
    assert exercise_class("Assisted Dip") == "assisted"
    assert exercise_class("Flat DB Bench Press") == "compound"
    assert exercise_class("Seated Cable Row") == "compound"
    assert exercise_class("Single-Arm Cable Pulldown") == "compound"
    assert exercise_class("Chest-Supported Rear-Delt Row") == "isolation"
    assert exercise_class("Straight-Arm Cable Pulldown") == "isolation"
    assert exercise_class("Cable External Rotation") == "isolation"
    assert exercise_class("Seated Lateral Raise") == "isolation"
    assert exercise_class("Hammer Strength Back Extension") == "bodyweight"
    assert exercise_class("Sit-Up Bench Crunch (knee test)") == "bodyweight"


def test_load_steps_by_class(athlete, library):
    assert load_rule("Flat DB Bench Press", library.find("Flat DB Bench Press"), athlete) == (5, None)
    assert load_rule("Seated Lateral Raise", library.find("Seated Lateral Raise"), athlete) == (2.5, 0.25)
    assert load_rule("Cable Curl", library.find("Cable Curl"), athlete) == (2.5, 0.25)
    assert load_rule("Assisted Pull-Up", library.find("Assisted Pull-Up"), athlete) == (5, None)


def test_pushups_are_bodyweight_and_on_their_own_program():
    from coach.profile import is_pushup_program

    assert exercise_class("Push-Ups") == "bodyweight" and exercise_class("Push-Up Max Test") == "bodyweight"
    assert is_pushup_program("Push-Up Max Test") and not is_pushup_program("Flat DB Bench Press")
