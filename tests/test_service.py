import importlib.util
import io
import json
from pathlib import Path

from coach.service import missing_settings, publishing, run_weekly, tracing_defaults
from evals import scripted

ROOT = Path(__file__).resolve().parent.parent


class FakeClient:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.saved = []

    def history(self, as_of, months):
        return self.snapshot

    def save_report(self, payload):
        self.saved.append(payload)
        return {"id": "r1"}


def test_a_weekly_run_saves_the_report_to_the_app(raw):
    client = FakeClient(raw("ready_to_progress"))
    out = run_weekly(client=client, llm=scripted.scripted_llm(), publish=True, use_langgraph=False)
    assert out["recommendation"] == "change" and out["published"] and not out["failed"]
    assert client.saved and client.saved[0]["decision"]["recommendation"] == "change"


def test_publishing_can_be_turned_off(raw):
    client = FakeClient(raw("fatigue_deload"))
    out = run_weekly(client=client, llm=scripted.scripted_llm(), publish=False, use_langgraph=False)
    assert out["change_level"] == 5 and not out["published"] and client.saved == []


def test_settings():
    assert missing_settings({}) == ["WORKOUT_AGENT_URL", "WORKOUT_AGENT_KEY", "ANTHROPIC_API_KEY"]
    assert missing_settings({"WORKOUT_AGENT_URL": "u", "WORKOUT_AGENT_KEY": "k", "ANTHROPIC_API_KEY": "a"}) == []
    assert publishing({}) is True and publishing({"COACH_PUBLISH": "false"}) is False
    env = {"LANGSMITH_API_KEY": "ls"}
    tracing_defaults(env)
    assert env["LANGSMITH_TRACING"] == "true" and env["LANGSMITH_PROJECT"] == "workout-coach"
    off = {"LANGSMITH_API_KEY": "ls", "LANGSMITH_TRACING": "false"}
    tracing_defaults(off)
    assert off["LANGSMITH_TRACING"] == "false"


def _handler_module():
    spec = importlib.util.spec_from_file_location("vercel_run", ROOT / "api" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _call(mod, headers, path="/api/run", method="GET"):
    h = mod.handler.__new__(mod.handler)
    h.headers = type("H", (), {"get": lambda self, k, d="": headers.get(k.lower(), headers.get(k, d))})()
    h.path = path
    h.wfile = io.BytesIO()
    sent = {}
    h.send_response = lambda s: sent.update(status=s)
    h.send_header = lambda *a: None
    h.end_headers = lambda: None
    getattr(h, f"do_{method}")()
    return sent["status"], json.loads(h.wfile.getvalue())


def test_only_the_scheduler_can_start_a_run(monkeypatch, raw):
    mod = _handler_module()
    for k in ("WORKOUT_AGENT_URL", "WORKOUT_AGENT_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    status, body = _call(mod, {"authorization": "Bearer " + "s" * 32})
    assert status == 500 and "ANTHROPIC_API_KEY" in body["error"]
    for k in ("WORKOUT_AGENT_URL", "WORKOUT_AGENT_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv("CRON_SECRET", raising=False)
    assert _call(mod, {})[0] == 500
    monkeypatch.setenv("CRON_SECRET", "s" * 32)
    assert _call(mod, {})[0] == 401
    assert _call(mod, {"authorization": "Bearer wrong"})[0] == 401
    assert _call(mod, {"authorization": "Bearer " + "s" * 32}, "/api/run?as_of=nope")[0] == 400
    calls = []
    monkeypatch.setattr(mod, "run_weekly", lambda as_of: calls.append(as_of) or {"recommendation": "hold"})
    status, body = _call(mod, {"authorization": "Bearer " + "s" * 32}, "/api/run?as_of=2026-11-27")
    assert status == 200 and calls == ["2026-11-27"] and body["recommendation"] == "hold"


def test_the_vercel_config_runs_weekly_from_the_entrypoint():
    cfg = json.loads((ROOT / "vercel.json").read_text())
    assert cfg["crons"] == [{"path": "/api/run", "schedule": "0 4 * * 6"}]
    import tomllib

    assert tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["vercel"]["entrypoint"] == "api.run:handler"
    reqs = (ROOT / "requirements.txt").read_text()
    for dep in ("pydantic", "pyyaml", "jinja2", "anthropic", "langgraph", "langsmith"):
        assert dep in reqs


def test_a_run_from_the_app_needs_the_owners_sign_in(monkeypatch):
    mod = _handler_module()
    monkeypatch.setenv("CRON_SECRET", "s" * 32)
    for k in ("WORKOUT_AGENT_URL", "WORKOUT_AGENT_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(k, "x")
    calls = []
    monkeypatch.setattr(mod, "run_weekly", lambda as_of: calls.append(as_of) or {"recommendation": "hold"})
    who = {"key": "me"}

    class FakeClient:
        def __init__(self, bearer=None, **_):
            self.bearer = bearer

        def whoami(self):
            return who.get(self.bearer, who["key"]) if self.bearer else who["key"]

    monkeypatch.setattr(mod, "AppClient", FakeClient)
    token = "t" * 40
    who[token] = "me"
    status, body = _call(mod, {"authorization": f"Bearer {token}"}, method="POST")
    assert status == 200 and calls == [None]
    who[token] = "someone-else"
    status, body = _call(mod, {"authorization": f"Bearer {token}"}, method="POST")
    assert status == 403 and len(calls) == 1
    # A sign-in on a GET (the schedule's way in) is never enough.
    who[token] = "me"
    assert _call(mod, {"authorization": f"Bearer {token}"})[0] == 401


def test_the_browser_check_is_answered(monkeypatch):
    mod = _handler_module()
    h = mod.handler.__new__(mod.handler)
    sent, headers = {}, {}
    h.send_response = lambda s: sent.update(status=s)
    h.send_header = lambda k, v: headers.update({k: v})
    h.end_headers = lambda: None
    h.do_OPTIONS()
    assert sent["status"] == 204 and headers["Access-Control-Allow-Origin"] == "*" and "POST" in headers["Access-Control-Allow-Methods"]
