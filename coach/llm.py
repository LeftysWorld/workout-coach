"""One way to ask a model for structured output, with a real implementation and a scripted one.

Every agent asks for JSON matching a pydantic model. The answer is parsed and validated; a reply that
doesn't validate gets one retry with the validation error attached. Tests and the offline evals use
`ScriptedLLM`, so the whole pipeline runs without an API key.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Optional, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

# The model for each agent, by what its job needs:
# - analyst: reads the whole history and makes the judgment calls (ready, too heavy, hurting, a lighter
#   week due; when to overrule the code's signals). The hardest thinking: the most capable model.
# - critic: weighs the trade-offs and decides whether a change is worth it. Judgment again.
# - planner: turns the read into 2–3 options in a strict format, checked by the rules in code. A strong,
#   faster model is enough.
# - judge (evals only): grades the coach's answers, so it should be at least as capable as the coach.
DEFAULT_MODELS: dict[str, str] = {
    "analyst": "claude-opus-5-5",
    "critic": "claude-opus-5-5",
    "planner": "claude-sonnet-5-5",
    "judge": "claude-opus-5-5",
}
FALLBACK_MODEL = "claude-sonnet-5-5"


def models_from_env(env: Optional[dict] = None) -> dict[str, str]:
    """Each agent's model. COACH_MODEL_<AGENT> (e.g. COACH_MODEL_PLANNER) sets one agent; COACH_MODEL sets
    every agent that hasn't its own; otherwise the defaults above."""
    env = os.environ if env is None else env
    every = (env.get("COACH_MODEL") or "").strip()
    out = {}
    for agent, default in DEFAULT_MODELS.items():
        own = (env.get(f"COACH_MODEL_{agent.upper()}") or "").strip()
        out[agent] = own or every or default
    return out


def describe(models: dict[str, str]) -> str:
    """'analyst=claude-opus-5-5,critic=…,planner=…': stored with each report, so any report says what made it."""
    return ",".join(f"{a}={models[a]}" for a in ("analyst", "planner", "critic") if a in models)


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    model: str

    def complete_json(self, *, agent: str, system: str, user: str, schema: type[T]) -> T: ...


def extract_json(text: str) -> Any:
    """The JSON object in a reply: the whole reply (structured output), a ```json block, or the
    outermost {...}."""
    try:
        return json.loads(text)
    except ValueError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = fence.group(1) if fence else text[text.find("{") : text.rfind("}") + 1]
    if not raw:
        raise LLMError("The reply had no JSON object.")
    return json.loads(raw)


def schema_hint(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(by_alias=True), separators=(",", ":"))


def _traceable(name: str, model: str = ""):
    """LangSmith tracing when it's installed and configured; a no-op otherwise."""
    try:
        from langsmith import traceable  # type: ignore

        return traceable(name=name, run_type="llm", metadata={"ls_provider": "anthropic", "ls_model_name": model} if model else None)
    except Exception:  # pragma: no cover - langsmith missing
        return lambda f: f


class AnthropicLLM:
    """Claude through the Anthropic API, each agent on its own model (see DEFAULT_MODELS).

    No sampling settings (temperature and the like): the current SDK (2.x) no longer takes them and
    refuses the call. Steady advice week to week comes from the facts, the governor and the evals'
    repeats, not from a low temperature."""

    def __init__(self, models: Optional[dict[str, str]] = None, max_tokens: int = 8000, model: Optional[str] = None):
        try:
            import anthropic  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise LLMError("pip install anthropic (it's in pyproject.toml)") from e
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        # `model` (one for every agent) is kept for scripts that pass one; otherwise per agent.
        self.models = {a: model for a in DEFAULT_MODELS} if model else (models or models_from_env())
        self.model = describe(self.models)
        self.max_tokens = max_tokens
        # Models that turned down structured output once: plain JSON for them from then on.
        self._plain: set[str] = set()

    def model_for(self, agent: str) -> str:
        return self.models.get(agent) or FALLBACK_MODEL

    def _output_config(self, schema: type[BaseModel]) -> dict:
        """Structured output: the API holds the reply to the schema, so it always parses."""
        raw = schema.model_json_schema(by_alias=True)
        transform = getattr(self._anthropic, "transform_schema", None)
        return {"format": {"type": "json_schema", "schema": transform(raw) if transform else raw}}

    def _ask(self, model: str, system: str, messages: list[dict], schema: type[BaseModel]) -> str:
        """One reply's text. Structured output when the model takes it; plain text otherwise."""
        kwargs: dict[str, Any] = {"model": model, "max_tokens": self.max_tokens, "system": system, "messages": messages}
        if model not in self._plain:
            try:
                reply = self.client.messages.create(**kwargs, output_config=self._output_config(schema))
            except (TypeError, self._anthropic.BadRequestError):
                # An older SDK (no output_config) or a schema/model the API won't constrain: ask for
                # plain JSON instead, and keep doing that for this model.
                self._plain.add(model)
                reply = self.client.messages.create(**kwargs)
        else:
            reply = self.client.messages.create(**kwargs)
        stop = getattr(reply, "stop_reason", None)
        if stop == "max_tokens":
            raise LLMError(f"the reply ran past {self.max_tokens} tokens and was cut off")
        if stop == "refusal":
            raise LLMError("the model declined to answer")
        return "".join(getattr(b, "text", "") for b in reply.content)

    def complete_json(self, *, agent: str, system: str, user: str, schema: type[T]) -> T:
        model = self.model_for(agent)

        @_traceable(f"{agent}", model)
        def run(system: str, user: str) -> T:
            instructions = f"{user}\n\nAnswer with one JSON object only, matching this JSON Schema:\n{schema_hint(schema)}"
            messages = [{"role": "user", "content": instructions}]
            text = self._ask(model, system, messages, schema)
            for attempt in range(2):
                try:
                    return schema.model_validate(extract_json(text))
                except (ValidationError, ValueError, LLMError) as e:
                    if attempt == 1:
                        raise LLMError(f"{agent} ({model}): the reply didn't match the schema twice: {e}") from e
                    messages += [{"role": "assistant", "content": text}, {"role": "user", "content": f"That didn't validate: {e}\nSend the corrected JSON object only."}]
                    text = self._ask(model, system, messages, schema)
            raise LLMError("unreachable")

        return run(system, user)


Script = dict[str, list[Any]]


class ScriptedLLM:
    """Answers from a script: agent name → a list of replies, used in order (the last one repeats).
    A reply is a dict, or a function of the user prompt that returns a dict. Records every call."""

    def __init__(self, script: Script, model: str = "scripted"):
        self.script = {k: list(v) for k, v in script.items()}
        self.model = model
        self.calls: list[dict] = []

    def complete_json(self, *, agent: str, system: str, user: str, schema: type[T]) -> T:
        self.calls.append({"agent": agent, "system": system, "user": user})
        replies = self.script.get(agent)
        if not replies:
            raise LLMError(f"No scripted reply for {agent}")
        reply = replies.pop(0) if len(replies) > 1 else replies[0]
        data = reply(user) if callable(reply) else reply
        return schema.model_validate(data)

    def count(self, agent: str) -> int:
        return sum(1 for c in self.calls if c["agent"] == agent)


Factory = Callable[[], LLM]
