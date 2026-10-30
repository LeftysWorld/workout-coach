"""A scripted stand-in for the model: plain rules that follow the skills, reading the same prompts.

Two uses:
- Run the whole pipeline (and the eval harness) with no API key: `coach run --scripted`, `coach evals --scripted`.
- A floor for the real agents: on the scenarios, the model should do at least as well as these rules.
It is not the coach. It can't read notes, weigh trade-offs or explain itself well.
"""

from __future__ import annotations

import json
import re

from coach.llm import ScriptedLLM

PAIN_WORDS = re.compile(r"\b(pain|hurt|hurts|felt off|knee|elbow|shoulder)\b", re.I)


def section(user: str, title: str):
    m = re.search(rf"## {re.escape(title)}[^\n]*\n(.*?)(?=\n\n## |\Z)", user, re.S)
    return json.loads(m.group(1)) if m else None


def _where(facts: dict, exercise: str):
    for w in facts["workouts"]:
        for e in w["exercises"]:
            if e["name"].lower() == exercise.lower():
                return w, e
    return None, None


def _pain(facts: dict, e: dict) -> bool:
    if (e.get("pain_flags_4w") or 0) > 0:
        return True
    name = e["exercise"].lower()
    return any(PAIN_WORDS.search(c["text"]) and (name.split(" (")[0].split()[-1] in c["text"].lower()) for c in facts.get("comments", []) if c["source"] in ("session_note", "exercise_note"))


def _ratio(f: dict) -> float:
    r = (f.get("program_signals") or {}).get("consistency_ratio")
    return 1.0 if r is None else r


def analyst(user: str) -> dict:
    f = section(user, "Facts")
    assert "workouts" not in f, "the analyst must not see the plan"
    reads = []
    for e in f["exercises"]:
        if not e.get("workouts"):
            continue
        if _pain(f, e):
            v = "pain"
        elif (e.get("sessions") or 0) < 3:
            v = "too_early"
        elif e.get("too_heavy"):
            v = "too_heavy"
        elif e.get("ready_to_add_weight"):
            v = "ready_to_progress"
        elif e.get("stalled"):
            v = "stalled"
        elif (e.get("e1rm_trend_pct") or 0) > 0:
            v = "progressing"
        else:
            v = "holding"
        reads.append({"exercise": e["exercise"], "verdict": v, "evidence": []})
    block = f["block"]
    ps = f.get("program_signals") or {}
    stalled = sum(1 for r in reads if r["verdict"] == "stalled")
    due = bool(block.get("at_block_end")) and stalled >= max(2, len(reads) // 2)
    deload = bool(ps.get("deload_suggested"))
    less = _ratio(f) < 0.8
    return {
        "summary": "Training less than usual is the main story this week." if less else ("The same weights are feeling harder across the board: time to back off for a week." if deload else "Workouts are happening; the question is which lifts are ready."),
        "consistency": "Fewer workouts than usual lately." if less else "Training as often as usual.",
        "recovery": "Wearing down: the same weights feel harder." if deload else ("Something hurt; ease off it." if any(r["verdict"] == "pain" for r in reads) else "No sign of under-recovery."),
        "program_fit": "Most lifts have stalled at a block's end." if due else "The program still fits.",
        "deload_due": deload,
        "deload_reason": "; ".join(ps.get("deload_signals") or []),
        "program_due_for_change": due and not deload,
        "program_change_reason": "Most lifts flat for weeks at a block's end." if due else "",
        "exercises": reads,
        "flags": [],
    }


def planner(user: str) -> dict:
    f = section(user, "Facts")
    a = section(user, "Assessment (from the analyst)")
    allowed = section(user, "Exercises you may add or swap in (nothing else)") or []
    by = {e["exercise"].lower(): e for e in f["exercises"]}
    small, big = [], []

    def change(kind: str, ex: str, frm: dict, to: dict, reason: str) -> dict | None:
        w, _ = _where(f, ex)
        return None if w is None else {"workout": w["title"], "action_id": w["action_id"], "type": kind, "exercise": ex, "from": frm, "to": to, "reason": reason}

    for r in a["exercises"]:
        ex, v = r["exercise"], r["verdict"]
        e = by.get(ex.lower(), {})
        _, plan = _where(f, ex)
        if not plan:
            continue
        if v == "pain":
            c = change("remove", ex, {"name": ex}, {}, "It hurt: take it out.") if e.get("trial") else None
            if c is None:
                alt = next((x["name"] for x in allowed if x["pattern"] == e.get("pattern") and x["name"].lower() != ex.lower() and not x.get("trial")), None)
                c = change("swap", ex, {"name": ex}, {"name": alt, "sets": plan["sets"], "reps_min": plan["reps_min"], "reps_max": plan["reps_max"]}, "It hurt: swap it for a gentler one.") if alt else change("remove", ex, {"name": ex}, {}, "It hurt: take it out.")
            if c:
                small.append(c)
        elif v == "too_heavy":
            step = e.get("weight_step") or 5
            used = e.get("last_weight") or plan.get("weight")
            if used and used - step > 0:
                # From what was actually lifted, not the plan's number.
                c = change("load", ex, {"weight": plan.get("weight")}, {"weight": used - step}, f"Reps falling at a hard effort at {_n(used)}: one step lighter.")
            else:
                c = change("reps", ex, {"reps_min": plan["reps_min"], "reps_max": plan["reps_max"]}, {"reps_min": max(1, plan["reps_min"] - 2), "reps_max": max(2, plan["reps_max"] - 2)}, "Reps falling at a hard effort: a lower range for now.")
            if c:
                small.append(c)
        elif v == "ready_to_progress":
            if e.get("jump_too_big") or plan.get("weight") is None:
                c = change("reps", ex, {"reps_min": plan["reps_min"], "reps_max": plan["reps_max"]}, {"reps_min": plan["reps_max"], "reps_max": plan["reps_max"] + 3}, "Reps holding with reps to spare, and the next weight is too big a jump: more reps first.")
            else:
                step = e.get("weight_step") or 5
                base = max(plan["weight"], e.get("last_weight") or 0)
                c = change("load", ex, {"weight": plan["weight"]}, {"weight": base + step}, "Reps holding with reps to spare at this weight: one step up.")
            if c:
                small.append(c)
        elif v == "stalled":
            if plan["sets"] < 5:
                c = change("sets", ex, {"sets": plan["sets"]}, {"sets": plan["sets"] + 1}, "Flat for weeks: one more set.")
                if c:
                    small.append(c)
            alt = next((x["name"] for x in allowed if x["pattern"] == e.get("pattern") and x["name"].lower() != ex.lower() and not x.get("trial") and not _where(f, x["name"])[0]), None)
            if alt:
                c = change("swap", ex, {"name": ex}, {"name": alt, "sets": plan["sets"], "reps_min": plan["reps_min"], "reps_max": plan["reps_max"]}, "Flat for weeks: a fresh variation.")
                if c:
                    big.append(c)
    # Mid-block, at most one structural change; non-structural first; at most three changes.
    structural = [c for c in small if c["type"] in {"swap", "remove", "add"}]
    pain_first = sorted([c for c in small if c["type"] not in {"swap", "remove", "add"}], key=lambda c: 0 if "lighter" in c["reason"] else 1)
    small = (structural[:1] + pain_first)[:3]
    level = lambda cs: max(({"reps": 1, "load": 2, "sets": 3, "swap": 4, "remove": 4, "add": 4, "deload": 5}[c["type"]] for c in cs), default=0)  # noqa: E731
    options = [{"id": "hold", "label": "Hold: no change", "change_level": 0, "changes": []}]
    if small:
        options.append({"id": "small", "label": "Small adjustments", "change_level": level(small), "changes": small})
    if a.get("deload_due"):
        lighter = []
        for w in f["workouts"]:
            for x in w["exercises"]:
                if x["sets"] > 1:
                    lighter.append({"workout": w["title"], "action_id": w["action_id"], "type": "deload", "exercise": x["name"], "from": {"sets": x["sets"]}, "to": {"sets": x["sets"] - 1}, "reason": "A lighter week: one fewer set at the same weight."})
        if lighter:
            options.append({"id": "lighter", "label": "A lighter week", "change_level": 5, "changes": lighter})
    if a.get("program_due_for_change") and big:
        options.append({"id": "program", "label": "New program: fresh variations for stalled lifts", "change_level": 6, "changes": big[:3]})
    pain = any(r["verdict"] in ("pain", "too_heavy") for r in a["exercises"])
    rec = "hold"
    if a.get("deload_due"):
        rec = "lighter"
    elif pain and small:
        rec = "small"
    elif _ratio(f) >= 0.8 and a.get("program_due_for_change") and big:
        rec = "program"
    elif _ratio(f) >= 0.8 and small:
        rec = "small"
    return {"options": options, "recommended_option_id": rec}


def critic(user: str) -> dict:
    options = section(user, "Options (each already passed the rules check), with scores from the fixed reward function") or []
    f = section(user, "Facts")
    a = section(user, "Assessment") or {}
    ids = {o["id"] for o in options}
    pain_fix = next((o for o in options if any(c["type"] in {"remove", "swap"} and "hurt" in c["reason"] or "lighter" in c["reason"] and c["type"] == "load" for c in o["changes"])), None)
    lighter = next((o for o in options if o["change_level"] == 5), None)
    if a.get("deload_due") and lighter:
        chosen = lighter["id"]
    elif pain_fix:
        chosen = pain_fix["id"]
    elif _ratio(f) < 0.8:
        chosen = "hold"
    else:
        chosen = max(options, key=lambda o: (o.get("score") or 0, -o["change_level"]))["id"] if options else "hold"
    return {
        "chosen_option_id": chosen if chosen in ids else "hold",
        "verdict": "accept",
        "drop_exercises": [],
        "reasons": ["The chosen option fixes what the data points at and nothing else."],
        "would_change_mind": ["Fewer workouts than usual, or a pain flag, next week."],
    }


def _n(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def scripted_llm() -> ScriptedLLM:
    llm = ScriptedLLM({"analyst": [analyst], "planner": [planner], "critic": [critic]}, model="scripted-rules")
    return llm
