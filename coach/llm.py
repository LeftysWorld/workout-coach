"""One way to ask a model for structured output, with a real implementation and a scripted one.

Every agent asks for JSON matching a pydantic model. The answer is parsed and validated; a reply that
doesn't validate gets one retry with the validation error attached. Tests and the offline evals use
`ScriptedLLM`, so the whole pipeline runs without an API key.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.environ.get("COACH_MODEL", "claude-sonnet-5-5")


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    model: str

    def complete_json(self, *, agent: str, system: str, user: str, schema: type[T]) -> T: ...


def extract_json(text: str) -> Any:
    """The JSON object in a reply: a ```json block, or the outermost {...}."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = fence.group(1) if fence else text[text.find("{") : text.rfind("}") + 1]
    if not raw:
        raise LLMError("The reply had no JSON object.")
    return json.loads(raw)


def schema_hint(schema: type[BaseModel]) -> str:
    return json.dumps(schema.model_json_schema(by_alias=True), separators=(",", ":"))


def _traceable(name: str):
    """LangSmith tracing when it's installed and configured; a no-op otherwise."""
    try:
        from langsmith import traceable  # type: ignore

        return traceable(name=name, run_type="llm")
    except Exception:  # pragma: no cover - langsmith missing
        return lambda f: f


class AnthropicLLM:
    """Claude through the Anthropic API. Low temperature: the same week should get the same advice."""

    def __init__(self, model: str = DEFAULT_MODEL, temperature: float = 0.2, max_tokens: int = 4000):
        try:
            import anthropic  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise LLMError("pip install anthropic (it's in pyproject.toml)") from e
        self.client = anthropic.Anthropic()
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _ask(self, system: str, messages: list[dict]) -> str:
        reply = self.client.messages.create(model=self.model, max_tokens=self.max_tokens, temperature=self.temperature, system=system, messages=messages)
        return "".join(getattr(b, "text", "") for b in reply.content)

    def complete_json(self, *, agent: str, system: str, user: str, schema: type[T]) -> T:
        @_traceable(f"{agent}")
        def run(system: str, user: str) -> T:
            instructions = f"{user}\n\nAnswer with one JSON object only, matching this JSON Schema:\n{schema_hint(schema)}"
            messages = [{"role": "user", "content": instructions}]
            text = self._ask(system, messages)
            for attempt in range(2):
                try:
                    return schema.model_validate(extract_json(text))
                except (ValidationError, ValueError, LLMError) as e:
                    if attempt == 1:
                        raise LLMError(f"{agent}: the reply didn't match the schema twice: {e}") from e
                    messages += [{"role": "assistant", "content": text}, {"role": "user", "content": f"That didn't validate: {e}\nSend the corrected JSON object only."}]
                    text = self._ask(system, messages)
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
