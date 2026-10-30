---
name: progression
description: How to read strength progress from what was actually done (weight, reps, effort 1–10), and when to add weight, add reps, hold, or reduce.
---
## Progression, from what was actually done

**Effort is the key.** Each exercise is rated 1–10 by reps left on the last set: 10 = none left,
9 = one, 8 = two, 7 = three, 6 or less = plenty. Reps alone can't tell an easy 12 from an all-out
12; reps plus effort can. Most working sets should land at 7–9.

**Add weight** (one smallest step) when, at the same weight, the last two workouts were rated 8 or
lower and the reps held or rose, and either the last one was 7 or lower (3+ left) or the reps have
climbed since that weight started (`ready_to_add_weight` says this). One rated 6 or lower: the
weight is clearly too light.

**Add reps first** when the next weight is a big jump (`jump_too_big: true`, e.g. 12.5 → 17.5 lb is
40%): more reps per set, then a set, then the weight. Never jump more than about 10%.

**Hold** when reps are rising at an 8–9: progress is happening, let it continue. Hold when
the ratings are missing: no rating, no new weight.

**Reduce** (one step down, or fewer reps) when the weight is too heavy: at the same weight the reps
fell from one workout to the next and the last was rated 9–10 (`too_heavy`). Also when a lift was
rated 10 with reps below where they were: the weight is above what they can do with good form.
Never add weight to a lift rated 10 last time.

**Getting harder** (`getting_harder`): the same weight and reps rated higher than before. One lift:
watch it. Several at once: that's fatigue, not a weak lift (see fatigue-and-deload).

**Estimated max** (`e1rm`, Epley from weight × reps; `e1rm_adj` adds the reps left): a rough guide,
noisy week to week. Trust trends over 3+ weeks. Up = progressing. Flat for 3+ weeks with 3+ workouts
= stalled (`stalled: true`). Down 2+ weeks = regressing: look at consistency, recovery and notes first.

**Beginners progress fast** at first: most lifts move every week or two. A lift flat for 3+ weeks
despite steady training has stalled.

**Losing weight changes the bar.** While body weight drops (trend below about -0.5 lb a week),
holding strength is a good result and slow gains are normal. Don't pile on volume to force progress
during a cut.
