"""Assemble each agent's system prompt from its AGENT.md and the skills it lists.

agents/<name>/AGENT.md starts with a small header:

    ---
    name: planner
    skills: [change-ladder, exercise-selection, program-blocks]
    profile: [goals, injuries_and_limits]   # optional: only these parts of athlete.yaml
    ---

The body is the agent's role. Each listed skill's SKILL.md body is appended under "Skills", then
your rules from profile/athlete.yaml. `prompt_version()` is a hash of every file that shapes an
answer (agents, skills, profile), stored with each report so any report can be traced to its prompts.
"""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "agents"
SKILLS = ROOT / "skills"
PROFILE = ROOT / "profile"

FRONT = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _split(text: str) -> tuple[dict, str]:
    m = FRONT.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip()
            meta[k.strip()] = [x.strip() for x in v.strip("[]").split(",") if x.strip()] if v.startswith("[") else v
    return meta, text[m.end() :]


@lru_cache(maxsize=8)
def system_prompt(agent: str) -> str:
    meta, body = _split((AGENTS / agent / "AGENT.md").read_text())
    parts = [body.strip(), "", "# Skills"]
    for skill in meta.get("skills", []):
        _, skill_body = _split((SKILLS / skill / "SKILL.md").read_text())
        parts += ["", skill_body.strip()]
    profile = (PROFILE / "athlete.yaml").read_text().strip()
    keys = meta.get("profile")
    if keys:
        # Only the parts this agent needs (the analyst sees your goals and limits, not your schedule).
        import yaml

        data = yaml.safe_load(profile)
        profile = yaml.safe_dump({k: data[k] for k in keys if k in data}, sort_keys=False, allow_unicode=True).strip()
    parts += ["", "# The athlete's rules (profile/athlete.yaml). These are rules, not suggestions.", "```yaml", profile, "```"]
    return "\n".join(parts)


def skills_of(agent: str) -> list[str]:
    meta, _ = _split((AGENTS / agent / "AGENT.md").read_text())
    return list(meta.get("skills", []))


@lru_cache(maxsize=1)
def prompt_version() -> str:
    h = hashlib.sha256()
    for folder in (AGENTS, SKILLS, PROFILE):
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                h.update(str(f.relative_to(ROOT)).encode())
                h.update(f.read_bytes())
    return h.hexdigest()[:10]
