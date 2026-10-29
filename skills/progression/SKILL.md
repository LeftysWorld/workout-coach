---
name: progression
description: How to read strength progress for a beginner lifting upper body while losing weight, and how progress is added (reps, then weight).
---
## Progression

**Double progression** is the default: keep a weight until every planned set reaches the top of the
rep range, then add the smallest weight step and drop back to the bottom of the range.
- `top_of_range_streak` ≥ 2 (two sessions in a row at the top on every set) → ready for more weight,
  if the step is small enough (`jump_too_big: false`).
- `top_of_range_streak` = 1 → usually wait one more session, or add a rep at the bottom of the range.
- Lots of reps left in the tank (`avg_rir_2w` ≥ 3) with sets done → the weight is too light: progress.
- Near failure (`avg_rir_2w` < 1) → don't add weight yet, even at the top of the range.

**Small dumbbells.** When the smallest step is a big share of the weight (`jump_too_big: true`, e.g.
12.5 → 17.5 lb is 40%), progress with reps first (extend the range: 12–15 → 15–20), then a set,
then the weight. Never jump more than about 10%.

**Reading the estimated max** (`e1rm`, Epley from weight × reps): a rough guide, noisy week to week.
Trust trends over 3+ weeks, not single sessions. Up = progressing. Flat for 3+ weeks with 3+ sessions =
stalled (`stalled: true`). Down for 2+ weeks = regressing: look at attendance, recovery, notes first.

**Beginners progress fast** at first; most lifts should move up every week or two in the first months.
A lift that hasn't moved in 3+ weeks despite good attendance has stalled.

**Losing weight changes the bar.** While body weight drops (trend below about -0.5 lb a week),
holding strength is a good result and slow gains are normal. Don't treat a hold as failure and don't
pile on volume to force progress during a cut.
