---
name: progression
description: How each kind of lift progresses (compound, isolation, assisted, bodyweight), effort targets, stalls, and when to add reps, a set, load, or hold.
---
## Progression, by kind of lift

These are the person's own rules. The app uses the same rules for each workout's next targets, so
a change you suggest should be the next step these rules give, not a different idea.

**Every exercise has a class** (`class` in the facts):
- **compound**: presses, rows, pulldowns (flat DB bench, machine press, seated cable row).
- **isolation**: one joint (curls, triceps work, raises, flies, rear-delt work, straight-arm pulldown,
  external rotation).
- **assisted**: assisted pull-ups and dips. The logged weight is the assist: **lower is harder**.
- **bodyweight**: back extension, glute-ham, crunches.

**How each moves forward:**
- **Compound: reps, then load.** When every set reaches the top of the rep range, one standard step
  (5 lb dumbbells, one plate on a machine or cable) and back to the bottom of the range.
- **Isolation: reps, then a set, then load.** Every set at the top: add a set (up to 4). All sets at
  the top again: the small step (2.5 lb) and back to the original sets. If the small step is more
  than 25% of the weight (`jump_too_big`), slow the tempo instead (3 seconds down, 1 second pause).
- **Assisted: 5 lb less assist** once every set reaches the top. Never suggest more assist as
  progress; more assist only eases off (pain, or reps falling hard).
- **Bodyweight:** every set at the top, add a plate.
- **More than one day:** a load increase on one day carries to the same lift on the other days.
  Not for assisted lifts: each day keeps its own assist.
- **Failed jump:** if the first set after a jump falls below the bottom of the range, go back to the
  old weight and build reps again.

**Push-ups run their own program (Road to 100).** Saturday's max test (one set, as many perfect
reps as possible) sets the next Monday: max under 60 → 5 sets × 60%; 60–79 → 4 × 65%; 80+ → 3 × 70%
then 1 set to 2 short of max. A missed Monday repeats its numbers. Never suggest changing push-up
sets, reps or load: the app sets them. A test that drops or stays flat two Saturdays running is worth
naming (sleep, the home practice); a shoulder or wrist note on push-ups follows the pain rule. They
are bodyweight, so the 12-rep cap doesn't apply. The machine chest press is gone (it hurt the
shoulder): Thursday is a neutral-grip DB bench press instead.

**Effort targets** (effort 1–10 by reps left on the last set: 10 = none left, 9 = one, 8 = two, 7 = three):
- compound and assisted: 8–9 (1–2 reps left).
- isolation: 8–10 (0–2 left); the last set can go to 10.
- Lateral raises stay at 8–12 reps, never more than 12 (the shoulder rule). Progress them by sets,
  tempo or the small step, never by reps past 12.
- Rated 6 or lower: the weight is too light; rated 10 with reps falling: too heavy (`too_heavy`).
  Never add weight to a lift rated 10 with falling reps.

**Stall:** no more reps and no more load for 2 sessions in a row on the same lift. One stalled lift
needs a change to that lift (a set, tempo, or a swap in the same pattern), not a deload. Several at
once: see fatigue-and-deload.

**Hold** when reps are rising at an 8–9 (progress is happening), and when ratings are missing.

**Estimated max** (`e1rm`): a rough guide, noisy week to week. Trust trends over 3+ weeks.

**Losing weight changes the bar.** During the cut, holding strength is a good result and slow gains
are normal. Don't pile on volume to force progress.
