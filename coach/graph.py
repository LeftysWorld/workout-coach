"""The same pipeline as a LangGraph StateGraph, built from coach/flow.py's NODES and ROUTES.

With LANGSMITH_API_KEY and LANGSMITH_TRACING=true set, every run is traced in LangSmith: each node,
each model call, the state between them. Nothing here decides anything: change the flow in flow.py.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END as LG_END  # type: ignore
from langgraph.graph import StateGraph  # type: ignore

from .flow import END, NODES, ROUTES, START, Context, guarded, next_node


class GraphState(TypedDict, total=False):
    # LangGraph merges each node's partial update into the state; values are plain Python objects.
    snapshot: Any
    facts: dict
    skip_reason: str
    assessment: Any
    options: Any
    planner_tries: int
    passing: list
    rejected: dict
    violations_text: Any
    scores: dict
    verdict: Any
    critic_rounds: int
    critic_note: Any
    decision: Any
    report_md: str
    payload: dict
    published: Any
    error: str
    trace: str
    failed: bool


def build_graph(ctx: Context):
    g = StateGraph(GraphState)
    for name, fn in NODES.items():
        node = guarded(name, fn)
        g.add_node(name, lambda state, _n=node: _n(dict(state), ctx))
    g.set_entry_point(START)
    for name in NODES:
        targets = {t for t in _targets(name)}
        mapping = {t: (LG_END if t == END else t) for t in targets}
        g.add_conditional_edges(name, lambda state, _name=name: next_node(_name, dict(state)), mapping)
    return g.compile()


def _targets(name: str) -> list[str]:
    """Every node a route can lead to (for LangGraph's edge map): its normal next steps plus the failsafe."""
    route = ROUTES[name]
    nexts = {
        "gate": ["finalize", "analyst"],
        "governor": ["planner", "score"],
        "critic": ["planner", "finalize"],
    }.get(name, [route] if isinstance(route, str) else [])
    if name not in ("failsafe", "render", "publish"):
        nexts = [*nexts, "failsafe"]
    return nexts
