"""Run the pipeline: with LangGraph when it's installed (traced in LangSmith), or by walking the same
NODES and ROUTES directly (tests, evals, and anywhere LangGraph isn't available). Same steps either way."""

from __future__ import annotations

from typing import Any

from .flow import END, NODES, START, Context, State, guarded, next_node

MAX_STEPS = 40  # a loop can't run away: 3 planner tries and 1 critic revision fit easily


def run_plain(ctx: Context, state: State | None = None) -> State:
    state = dict(state or {})
    node = START
    path: list[str] = []
    for _ in range(MAX_STEPS):
        path.append(node)
        update = guarded(node, NODES[node])(state, ctx)
        state.update(update)
        node = next_node(node, state)
        if node == END:
            state["path"] = path
            return state
    raise RuntimeError(f"The pipeline didn't finish in {MAX_STEPS} steps: {' → '.join(path)}")


def run(ctx: Context, use_langgraph: bool = False) -> State:
    if use_langgraph:
        try:
            from .graph import build_graph

            app = build_graph(ctx)
        except ImportError:
            return run_plain(ctx)
        result: Any = app.invoke({}, config={"recursion_limit": MAX_STEPS, "run_name": "workout-coach"})
        return dict(result)
    return run_plain(ctx)
