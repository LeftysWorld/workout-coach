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
