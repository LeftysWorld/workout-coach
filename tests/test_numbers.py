from coach.numbers import allowed_numbers, filter_grounded, ungrounded


def test_numbers_must_come_from_the_data():
    allowed = allowed_numbers({"attendance_4w": 0.92, "e1rm_now": 133.3, "weight": 100, "next": 105, "as_of": "2026-11-27"})
    assert ungrounded("Attendance is 92% and your estimated max is 133.3.", allowed) == []
    assert ungrounded("Up from 100 to 105 is 5 lb.", allowed) == []
    assert ungrounded("Week 3 of 4, on Nov 27, 2026.", allowed) == []
    assert ungrounded("Your bench went up 12.5% this month.", allowed) == ["12.5"]
    kept, dropped = filter_grounded(["Hit 133.3 again.", "That's 40% stronger."], allowed)
    assert kept == ["Hit 133.3 again."] and dropped == ["That's 40% stronger."]
