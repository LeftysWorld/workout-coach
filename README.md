# workout-coach

A weekly AI review of my workouts. Every Friday night it reads my workout history from the
[six-month-plan](https://github.com/LeftysWorld/six-month-plan) app, decides whether next week's
workouts should change (often: no), and writes a report: what's going on, what to change or not,
and why. It never changes my plan. I read the report and decide.

## How it works

```
Friday night (GitHub Actions)
  load      the history snapshot, as of Friday, from the app's workout-agent function
  check     recompute key numbers; stop if the app's math and ours disagree
  facts     the compact view the agents read (code computes every number)
  gate      fewer than two weeks of data → "no recommendation", agents skipped
  analyst   per exercise: ready / progressing / holding / stalled / pain / too early
  planner   2–3 options for next week, always including "hold"
  governor  my rules, in code; broken rules go back to the planner (twice), then hold
  score     the reward function ranks the options that passed
  critic    argues for leaving things alone; accepts, trims, or asks for one revision
  finalize  numbers in the words are checked against the data
  render    the report (a fixed template)
  publish   one row in workout_reports (only when publishing is on)
Any failure → an honest "no recommendation this week" report.
```

**Change ladder:** 0 hold · 1 reps · 2 load · 3 sets · 4 swap one exercise · 5 lighter week ·
6 new program. Weekly check-ins stay small; bigger changes happen at the end of a 4-week block,
with evidence.

**Reward:** `0.35 consistency + 0.30 progression + 0.15 quality + 0.10 balance − 0.10 risk`
(`coach/score.py`, version `r3`). Fixed by me, never chosen by an agent.

**What it judges from:** what I actually did, never what was planned. Weights and reps per set, the
1–10 effort I give each exercise (10 = no reps left), pain flags and where, my notes, body weight and
body measurements (waist, chest, arms, shoulders). The analyst never sees the plan's targets or my
schedule; only the planner sees the plan, to write changes against it. From that history, code works
out the signals: ready for more weight, too heavy, the same weights getting harder, strength falling,
fewer workouts than my usual, a cut that's too fast, and when two or more line up, a lighter week.

**Access:** the agent's key opens exactly two doors, `GET /history` and `POST /reports`. It sees
workouts (plans and their history, sets, effort, pain, notes), body weight and body measurements
(unless turned off in the app) and past coach decisions. Nothing else in the app.

## Set up

1. **App side** (in six-month-plan, on main): run the migrations, deploy the `workout-agent`
   function and set its secrets. See `docs/WORKOUT_COACH.md` there.
2. **Here:**
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev]"
   cp .env.example .env    # fill in WORKOUT_AGENT_URL, WORKOUT_AGENT_KEY, ANTHROPIC_API_KEY
   set -a; source .env; set +a
   coach history --format md | head -40     # check access: the same report the app shows
   coach run                                 # dry run: writes out/report-<date>.md
   ```
3. **GitHub:** Settings → Secrets and variables → Actions.
   - Secrets: `WORKOUT_AGENT_URL`, `WORKOUT_AGENT_KEY`, `ANTHROPIC_API_KEY`, optionally `LANGSMITH_API_KEY`.
   - Variable: `COACH_PUBLISH` = `false` for the first 2–3 weeks (reports land in the run summary
     only), then `true` to save them to the app.

## Use it

| Command | What |
|---|---|
| `coach run` | Review this week (dry run). `--publish` saves it; `--as-of 2026-11-27` reviews a past week |
| `coach run --snapshot evals/fixtures/pain_note.json --scripted` | Try the pipeline offline with the scripted rules |
| `coach run --langgraph` | The same run through LangGraph, each step traced in LangSmith (try it once by hand before the weekly job uses it) |
| `coach history --format md` | Print exactly what the agent can see |
| `coach evals --scripted` | Every scenario with the scripted rules (CI runs this) |
| `coach evals --repeats 3` | Every scenario with the real agents, three times each (stability) |
| `coach backtest --from 2026-11-06 --to 2027-01-29` | Replay past Fridays against the simple rule |

To act on a report: open it in the app (Review → Workout report), copy it with **Copy for chat**, paste
it into Claude and ask for the changes. Then mark the report **Applied**, **Partly** or **Declined**.
The next run reads that.

## Change it

- **My rules** (knee, days, time, equipment, limits): `profile/athlete.yaml`. The governor enforces them.
- **Exercises the coach may suggest:** `profile/exercise_library.yaml`.
- **How an agent thinks:** `agents/<name>/AGENT.md`. **What it knows:** `skills/<name>/SKILL.md`.
- **Ask for a new program next run:** set `program.requested_program_change: true` in `profile/athlete.yaml`.

Every report records the prompt version (a hash of `agents/`, `skills/` and `profile/`) and the reward
version, so any report can be traced to what produced it. Rules for coding agents working on this
repo: `AGENTS.md`.
