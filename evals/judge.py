"""The AI grader for the coach's reasoning (evals/rubrics/rationale.md). Needs ANTHROPIC_API_KEY."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from coach.llm import AnthropicLLM

RUBRIC = (Path(__file__).parent / "rubrics" / "rationale.md").read_text()


class Grade(BaseModel):
    grounded: int = Field(ge=1, le=5)
    clear: int = Field(ge=1, le=5)
    trade_off: int = Field(ge=1, le=5)
    changeable: int = Field(ge=1, le=5)
    safe: int = Field(ge=1, le=5)
    passed: bool = Field(alias="pass")
    notes: str = ""


def judge(state: dict, llm: AnthropicLLM | None = None) -> Grade:
    llm = llm or AnthropicLLM()
    user = "## Facts\n" + json.dumps(state.get("facts", {}), default=str) + "\n\n## Decision\n" + json.dumps(state["decision"].to_payload(), default=str)
    return llm.complete_json(agent="judge", system=RUBRIC, user=user, schema=Grade)
