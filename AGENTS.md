# AGENTS.md: working on this repo

Instructions for any coding agent (Claude Code, Codex, …) changing this repo. The agents *inside*
the product are described in `agents/*/AGENT.md`; this file is about building them.

## What this is

A weekly review of one person's workouts. It reads a snapshot of their workout history from the
six-month-plan app, decides whether next week's workouts should change (most weeks: no), and writes
a report. It never changes the plan itself. A person reads the report and decides.

## Hard rules: don't break these

1. **The only door into the app is `coach/client.py`**: `GET /history` and `POST /reports` on the
   `workout-agent` Edge Function, with the agent key. Never add another endpoint, a Supabase client,
   the service key, or a direct database connection. If a feature needs more data, add it to the
   snapshot in the app repo (`supabase/functions/_shared/workout_history.ts`) and bump the schema.
2. **Numbers come from code.** Agents judge; `coach/metrics.py` computes. Never ask a model to do
   arithmetic, and keep `coach/numbers.py` checking every number in the output.
3. **The governor has the last word.** Any rule from `profile/athlete.yaml` is enforced in
   `coach/governor.py`, not only in a prompt. A new rule needs a governor check and a test.
4. **The reward function is fixed, and the person owns it.** Changing `coach/score.py` means
   bumping `REWARD_VERSION` and saying so in the commit.
5. **Failure is a report, never silence and never a half answer.** Keep `guarded()` and `failsafe` in
   `coach/flow.py` covering every node.

## Where things are

| Path | What |
|---|---|
| `coach/flow.py` | The pipeline: NODES and ROUTES, defined once |
| `coach/graph.py` / `coach/runner.py` | The same flow in LangGraph / walked directly (tests, evals) |
| `coach/snapshot.py` | Schema 1 of the app's snapshot (pydantic) |
| `coach/metrics.py` | Contract check, the facts the agents read, block position |
| `coach/governor.py` | Hard rules |
| `coach/score.py` | The reward function |
| `coach/agents.py`, `coach/prompts.py` | The three agents; prompt assembly and `prompt_version()` |
| `agents/<name>/AGENT.md` | Each agent's role, and the skills it loads |
| `skills/<name>/SKILL.md` | Knowledge modules: progression, the change ladder, exercise selection, pain, blocks, writing |
| `profile/athlete.yaml`, `profile/exercise_library.yaml` | The person's rules and the exercises the coach may use |
| `coach/render.py`, `coach/templates/` | The report |
| `evals/` | Scenarios (fixtures made by the app's own builder), evaluators, scripted rules, judge, backtest |

## Before you commit

```bash
pip install -e ".[dev]"
pytest -q                       # unit tests and the pipeline with the scripted rules
coach evals --scripted          # every scenario, scripted rules: must stay 12/12
```

If you changed anything under `agents/`, `skills/`, `profile/` or `coach/score.py`, also run the real
evals (`coach evals --repeats 3` with `ANTHROPIC_API_KEY`) and, when there's history to replay,
`coach backtest`. A change ships only if the scenarios still pass, the levels are stable across
repeats, and the backtest is at least as good as the simple rule.

New scenario: add a case to `evals/fixtures/generate.ts` (run it with `npx tsx` from a sibling
checkout of six-month-plan, so the fixture comes from the app's real builder), then an `Expect` in
`evals/scenarios.py`.

## Style

Plain words in anything the person reads (reports, rule messages, prompts). Short sentences.
No numbers in prose that aren't in the facts.
