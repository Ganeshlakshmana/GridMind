"""
agent/graph.py

Wires the 7 nodes into a LangGraph StateGraph and compiles it.

Graph topology:
    START
      │
      ▼
    monitor_node
      │
      ▼  (conditional via router)
    detect_node ──────────────────────────────────┐
      │                                            │ no anomalies
      ▼  (conditional via router)                 │
    triage_node                                    │
      │                                            │
      ▼  (conditional via router)                 │
    action_node ──── no actions ──────────────────┤
      │                                            │
      ▼                                            │
    verify_node                                    │
      │                                            │
      ▼  ◄────────────────────────────────────────┘
    report_node
      │
      ▼
     END

The router function (from nodes.py) drives all conditional edges.
compile() returns a callable graph — call it with an initial state dict.
"""

from langgraph.graph import END, START, StateGraph

from agent.nodes import (
    action_node,
    detect_node,
    monitor_node,
    report_node,
    router,
    triage_node,
    verify_node,
)
from agent.state import VPPState


def build_graph() -> StateGraph:
    """
    Construct and return the compiled LangGraph StateGraph.
    Call this once at startup and reuse the compiled graph across sessions.
    """
    g = StateGraph(VPPState)

    # ── Register nodes ────────────────────────────────────────────────────────
    g.add_node("monitor_node", monitor_node)
    g.add_node("detect_node",  detect_node)
    g.add_node("triage_node",  triage_node)
    g.add_node("action_node",  action_node)
    g.add_node("verify_node",  verify_node)
    g.add_node("report_node",  report_node)

    # ── Entry edge ────────────────────────────────────────────────────────────
    g.add_edge(START, "monitor_node")

    # ── Conditional edges driven by router ───────────────────────────────────
    # After monitor: always go to detect
    g.add_conditional_edges(
        "monitor_node",
        router,
        {
            "detect_node":  "detect_node",
            "report_node":  "report_node",   # error fast-path
        },
    )

    # After detect: go to triage if anomalies found, else report
    g.add_conditional_edges(
        "detect_node",
        router,
        {
            "triage_node":  "triage_node",
            "report_node":  "report_node",
        },
    )

    # After triage: go to action if plan has work, else report
    g.add_conditional_edges(
        "triage_node",
        router,
        {
            "action_node":  "action_node",
            "report_node":  "report_node",
        },
    )

    # After action: always verify
    g.add_conditional_edges(
        "action_node",
        router,
        {
            "verify_node":  "verify_node",
            "report_node":  "report_node",   # error fast-path
        },
    )

    # After verify: always report
    g.add_edge("verify_node", "report_node")

    # ── Exit edge ─────────────────────────────────────────────────────────────
    g.add_edge("report_node", END)

    return g.compile()


# Module-level compiled graph — import and reuse across the application
graph = build_graph()