---
name: fatigue-and-deload
description: The scheduled lighter week (every 8 weeks, or sooner when several lifts stall), and reading fatigue from effort, strength, consistency and the cut.
---
## Fatigue and the lighter week

**The app schedules lighter weeks itself.** Counting from the program start (Oct 26, 2026), every
8th week is a lighter week, or sooner when 3 or more lifts have stalled (from the 4th week of a
block). The app switches to it automatically; the person can skip one. A lighter week is: half the
sets, the same weights, effort about 6–7 (3–4 reps left). The week after, back to normal at the same
weights.

So when a week shows about half the sets at the same weights, that was a lighter week: don't read
it as a drop in training or strength.

**Between scheduled ones, evidence can still call for one** (a deload, level 5). The signals
(worked out in code, in `program_signals.deload_signals`):
- the same weights feel harder on several lifts (`getting_harder` or `too_heavy` on 3+)
- estimated strength falling on several lifts (2+ down 3% or more over 3 weeks)
- whole workouts rated harder than usual (1.5+ higher than their usual, or 9+)
- fewer workouts than their usual (under three quarters of it)
- losing weight faster than 1% of body weight a week

**One signal is a watch, two or more is a lighter week** (`deload_suggested`). Notes count: "wiped
out", "sleeping badly", "sore all week" alongside one signal is enough. A single bad workout isn't.
If a scheduled lighter week is only a week or two away, say so rather than adding another.

**Not a deload:** one lift stalled while the rest move (that lift needs a change, see progression),
or fewer workouts because of travel or a busy week with effort normal.

**After one:** if the same signals come back within 3–4 weeks, the program itself is too much
(volume, or the cut is too aggressive). Say so; that's a program question, not another deload.

**The cut ends at 175 lb** (a 7-day average). The app asks the person before switching to building;
the coach doesn't make that call. Until then, judge progress as a cut.
