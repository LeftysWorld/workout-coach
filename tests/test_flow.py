import json

import pytest

from coach.flow import Context
from coach.llm import LLMError, ScriptedLLM
from coach.runner import run_plain
from evals import scripted
from evals.evaluators import evaluate, payload_valid
from evals.scenarios import SCENARIOS, by_name


def run(raw_snapshot, llm, athlete, library, publish=None):
    return run_plain(Context(llm=llm, athlete=athlete, library=library, snapshot_json=raw_snapshot, publish=publish))


@pytest.mark.parametrize("name", [s.name for s in SCENARIOS])
def test_every_scenario_passes_with_the_scripted_rules(raw, athlete, library, name):
    state = run(raw(name), scripted.scripted_llm(), athlete, library)
    failed = {k: v[1] for k, v in evaluate(state, by_name(name).expect).items() if not v[0]}
    assert not failed, failed


def test_happy_path_walks_every_step_and_publishes(raw, athlete, library):
    sent = []
    state = run(raw("ready_to_progress"), scripted.scripted_llm(), athlete, library, publish=lambda p: sent.append(p) or {"id": "r1"})
    assert state["path"] == ["load", "check", "facts", "gate", "analyst", "planner", "governor", "score", "critic", "finalize", "render", "publish"]
    assert sent and sent[0]["decision"]["recommendation"] == "change"
    assert sent[0]["snapshot_hash"] == raw("ready_to_progress")["meta"]["fingerprint"]
    assert payload_valid(state)[0]


def test_too_little_data_skips_the_agents(raw, athlete, library):
    llm = scripted.scripted_llm()
    state = run(raw("too_little_data"), llm, athlete, library)
    assert state["decision"].recommendation == "none"
    assert llm.calls == []
    assert "too early" in state["report_md"]


def test_rule_breaking_proposals_go_back_to_the_planner_then_hold(raw, athlete, library):
    bad = {"options": [{"id": "hold", "label": "Hold", "change_level": 0, "changes": []}, {"id": "squat", "label": "Squats", "change_level": 4, "changes": [{"workout": "Mon: Chest + Back", "type": "swap", "exercise": "Seated Lateral Raise", "from": {"name": "Seated Lateral Raise"}, "to": {"name": "Goblet Squat"}, "reason": "legs"}]}], "recommended_option_id": "squat"}
    llm = ScriptedLLM({"analyst": [scripted.analyst], "planner": [bad], "critic": [scripted.critic]})
    state = run(raw("comment_conflict"), llm, athlete, library)
    assert llm.count("planner") == 3  # the first proposal and two fixes
    assert any("knee" in m for msgs in state["rejected"].values() for m in msgs)
    assert "knee" in llm.calls[2]["user"] and "broke these rules" in llm.calls[2]["user"]
    assert state["decision"].recommendation == "hold"


def test_a_fixed_proposal_is_used(raw, athlete, library):
    bad = {"options": [{"id": "hold", "label": "Hold", "change_level": 0, "changes": []}, {"id": "big", "label": "Big jump", "change_level": 2, "changes": [{"workout": "Mon: Chest + Back", "type": "load", "exercise": "Flat DB Bench Press", "from": {"weight": 50}, "to": {"weight": 60}, "reason": "go"}]}], "recommended_option_id": "big"}
    llm = ScriptedLLM({"analyst": [scripted.analyst], "planner": [bad, scripted.planner], "critic": [scripted.critic]})
    state = run(raw("ready_to_progress"), llm, athlete, library)
    assert state["planner_tries"] == 2
    assert state["decision"].changes[0].to.weight == 55


def test_the_critic_can_ask_for_one_revision(raw, athlete, library):
    revise = {"chosen_option_id": "hold", "verdict": "revise", "reasons": ["Try reps first"], "revise_instructions": "Use reps, not load, on bench."}
    llm = ScriptedLLM({"analyst": [scripted.analyst], "planner": [scripted.planner], "critic": [revise, revise]})
    state = run(raw("ready_to_progress"), llm, athlete, library)
    assert llm.count("planner") == 2 and llm.count("critic") == 2
    assert "Use reps, not load" in [c for c in llm.calls if c["agent"] == "planner"][1]["user"]
    assert state["verdict"].verdict == "accept"  # a second "revise" is turned into accept


def test_the_critic_can_downgrade(raw, athlete, library):
    down = {"chosen_option_id": "small", "verdict": "downgrade", "drop_exercises": ["Flat DB Bench Press"], "reasons": ["One thing at a time."]}
    llm = ScriptedLLM({"analyst": [scripted.analyst], "planner": [scripted.planner], "critic": [down]})
    state = run(raw("ready_to_progress"), llm, athlete, library)
    assert all(c.exercise != "Flat DB Bench Press" for c in state["decision"].changes)


def test_any_failure_becomes_an_honest_report(raw, athlete, library):
    def broken(_user):
        raise LLMError("the model is down")

    llm = ScriptedLLM({"analyst": [broken]})
    state = run(raw("ready_to_progress"), llm, athlete, library)
    assert state["failed"] and state["decision"].recommendation == "none"
    assert "the model is down" in state["report_md"]
    assert payload_valid(state)[0]


def test_ungrounded_numbers_are_dropped_from_the_report(raw, athlete, library):
    lying = lambda user: {**scripted.critic(user), "reasons": ["Your bench is up 37.7% in a month.", "Bench hit the top of the range."]}  # noqa: E731
    llm = ScriptedLLM({"analyst": [scripted.analyst], "planner": [scripted.planner], "critic": [lying]})
    state = run(raw("ready_to_progress"), llm, athlete, library)
    assert "37.7" not in state["report_md"]
    assert "Bench hit the top of the range." in state["report_md"]
    assert "dropped because they cited numbers not in your data" in state["report_md"]


def test_the_report_has_its_sections_and_a_usable_change_list(raw, athlete, library):
    state = run(raw("ready_to_progress"), scripted.scripted_llm(), athlete, library)
    md = state["report_md"]
    for heading in ["# Workout coach · week of", "## Where you are", "## What to change", "## Options considered", "## The change list"]:
        assert heading in md
    block = md.split("```json")[1].split("```")[0]
    assert json.loads(block)["changes"][0]["exercise"] == "Flat DB Bench Press"
