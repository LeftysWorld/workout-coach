import io
import json

from coach import client as client_mod
from coach.client import AppClient
from coach.prompts import prompt_version, skills_of, system_prompt


class FakeResponse(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_client_only_uses_the_agent_key_and_two_routes(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout):
        seen.append(req)
        return FakeResponse(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(client_mod.urllib.request, "urlopen", fake_urlopen)
    c = AppClient(url="https://x.supabase.co/functions/v1/workout-agent/", key="k" * 40)
    c.history("2026-11-27", 6)
    c.save_report({"as_of": "2026-11-27"})
    assert seen[0].full_url == "https://x.supabase.co/functions/v1/workout-agent/history?as_of=2026-11-27&months=6"
    assert seen[0].get_header("X-agent-key") == "k" * 40 and seen[0].get_method() == "GET"
    assert seen[1].full_url.endswith("/reports") and seen[1].get_method() == "POST"
    assert all(not r.get_header("Authorization") for r in seen)


def test_every_agent_loads_its_skills_and_the_rules():
    for agent in ("analyst", "planner", "critic"):
        prompt = system_prompt(agent)
        assert "The athlete's rules" in prompt and "banned_patterns" in prompt
        assert skills_of(agent)
    assert "## The change ladder" in system_prompt("planner")
    assert len(prompt_version()) == 10


def test_the_analyst_sees_goals_and_limits_not_the_schedule():
    analyst = system_prompt("analyst")
    assert "banned_patterns" in analyst and "goals" in analyst
    assert "days_per_week" not in analyst and "session_minutes" not in analyst
    assert "days_per_week" in system_prompt("planner")
    assert "## Fatigue and the lighter week" in analyst and "## Body weight and measurements" in analyst


def test_each_agent_gets_the_model_its_job_needs():
    from coach.llm import DEFAULT_MODELS, describe, models_from_env

    assert DEFAULT_MODELS["analyst"] == DEFAULT_MODELS["critic"] == "claude-opus-5-5"
    assert DEFAULT_MODELS["planner"] == "claude-sonnet-5-5"
    assert models_from_env({}) == DEFAULT_MODELS
    # One for everything, then one agent on its own.
    every = models_from_env({"COACH_MODEL": "claude-sonnet-5-5"})
    assert set(every.values()) == {"claude-sonnet-5-5"}
    mixed = models_from_env({"COACH_MODEL": "claude-sonnet-5-5", "COACH_MODEL_ANALYST": "claude-opus-5-5"})
    assert mixed["analyst"] == "claude-opus-5-5" and mixed["critic"] == "claude-sonnet-5-5"
    assert describe(DEFAULT_MODELS) == "analyst=claude-opus-5-5,planner=claude-sonnet-5-5,critic=claude-opus-5-5"


def test_the_real_client_asks_each_agent_on_its_own_model(monkeypatch):
    import sys
    import types

    from coach.decision import CriticVerdict
    from coach.llm import AnthropicLLM

    asked = []

    class Messages:
        def create(self, *, model, **_):
            asked.append(model)
            text = '{"chosen_option_id": "hold", "verdict": "accept"}'
            return types.SimpleNamespace(content=[types.SimpleNamespace(text=text)])

    fake = types.ModuleType("anthropic")
    fake.Anthropic = lambda: types.SimpleNamespace(messages=Messages())
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    llm = AnthropicLLM(models={"analyst": "claude-opus-5-5", "planner": "claude-sonnet-5-5", "critic": "claude-opus-5-5"})
    llm.complete_json(agent="critic", system="s", user="u", schema=CriticVerdict)
    llm.complete_json(agent="planner", system="s", user="u", schema=CriticVerdict)
    assert asked == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert "analyst=claude-opus-5-5" in llm.model
