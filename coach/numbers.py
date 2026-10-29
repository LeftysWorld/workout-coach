"""Every number in the coach's words must come from your data.

The model is good at judgment and bad at arithmetic, and a made-up "your bench went up 12%" is the
fastest way to lose trust in a report. So: collect every number the agents were shown (facts, the
proposed changes), allow the obvious restatements (a share as a percentage, rounding), and flag
any other number in a sentence. Flagged sentences are dropped from the report, and the run notes it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

NUM = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?![\w])")
ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
# Small counts ("one set", "2 weeks", "3+") are part of ordinary speech and the change ladder.
FREE = {float(n) for n in range(0, 11)}


def _walk(value: Any, out: set[float]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        v = float(value)
        out.update({v, round(v, 1), round(v), abs(v)})
        if -1.5 <= v <= 1.5:  # shares (0.92) are spoken as percentages (92%)
            out.update({round(v * 100), round(v * 100, 1), abs(round(v * 100))})
        return
    if isinstance(value, str):
        for y, m, dd in ISO.findall(value):
            out.update({float(y), float(int(m)), float(int(dd))})
        for n in NUM.findall(ISO.sub(" ", value)):
            out.add(abs(float(n)))
        return
    if isinstance(value, dict):
        for v in value.values():
            _walk(v, out)
        return
    if isinstance(value, (list, tuple, set)):
        for v in value:
            _walk(v, out)


def allowed_numbers(facts: Any, changes: Any = None) -> set[float]:
    """Every number in the facts and the proposed changes, plus differences *within* the changes
    ("100 → 105 is 5 lb"). Differences between arbitrary facts aren't allowed: with hundreds of
    numbers around, almost any figure is the difference of some pair, and the check would mean nothing."""
    out: set[float] = set(FREE)
    _walk(facts, out)
    change_nums: set[float] = set()
    _walk(changes or [], change_nums)
    out |= change_nums
    vals = sorted(v for v in change_nums if 0 < v < 1000)
    for a in vals:
        for b in vals:
            if b > a:
                out.add(round(b - a, 1))
                if a > 0:
                    out.add(round((b - a) / a * 100))
    return out


def ungrounded(text: str, allowed: set[float]) -> list[str]:
    """The numbers in `text` that aren't in `allowed` (dates in the text are fine when they're in the data)."""
    bad = []
    for n in NUM.findall(ISO.sub(" ", text)):
        v = abs(float(n))
        if v in allowed or any(abs(v - a) <= 0.051 for a in allowed):
            continue
        bad.append(n)
    return bad


def filter_grounded(lines: Iterable[str], allowed: set[float]) -> tuple[list[str], list[str]]:
    """Split sentences into (kept, dropped)."""
    kept, dropped = [], []
    for line in lines:
        (dropped if ungrounded(line, allowed) else kept).append(line)
    return kept, dropped
