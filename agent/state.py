"""
agent/state.py

Defines VPPState — the single shared object threaded through every node
in the LangGraph graph. Each node reads from it and writes back to it.

Think of it as the agent's working memory for one complete session:
it starts nearly empty, accumulates findings as nodes run, and ends
with a fully populated report ready for the operator.

Design rules:
  - All fields are Optional with None defaults so the graph can be
    initialised with just a prompt and nothing else.
  - Nodes only write to their own output fields — they never mutate
    fields owned by another node.
  - The messages list follows LangChain's standard format so it can
    be passed directly to ChatAnthropic.bind_tools().
"""

from typing import Any, Optional
from typing_extensions import TypedDict


class VPPState(TypedDict, total=False):
    """
    Shared state for one GridMind agent session.

    Field ownership by node:
        messages        → all nodes (append-only)
        prompt          → set once by runner, never mutated
        fleet_summary   → monitor_node
        anomalies       → detect_node
        triage_plan     → triage_node
        actions_taken   → action_node
        verification    → verify_node
        report          → report_node
        session_id      → set once by runner
        error           → any node on failure
    """

    # ── Input ─────────────────────────────────────────────────────────────────
    prompt: str
    """The operator's natural language request that initiated this session."""

    session_id: str
    """UUID for this run — used by tracer and session dashboard."""

    # ── LangChain message history ─────────────────────────────────────────────
    messages: list[Any]
    """
    Full message history in LangChain format.
    Passed directly to the model on each LLM call.
    Nodes append; nothing deletes.
    """

    # ── Node outputs ──────────────────────────────────────────────────────────
    fleet_summary: Optional[dict]
    """
    Output of get_fleet_summary().
    Set by monitor_node. Contains total, by_status, systems_needing_attention.
    """

    anomalies: Optional[dict]
    """
    Output of detect_anomalies().
    Set by detect_node. Contains total_anomalies and anomalies list.
    """

    triage_plan: Optional[dict]
    """
    LLM-generated triage decision.
    Set by triage_node. Schema:
    {
        "to_resolve":  [{"system_id": str, "action": str, "notes": str}],
        "to_escalate": [{"system_id": str, "reason": str, "severity": str}],
        "to_monitor":  [str],   # system_ids — watch but no action yet
        "rationale":   str,     # LLM's reasoning, included in final report
    }
    """

    actions_taken: Optional[list[dict]]
    """
    Results of every resolve_issue / escalate_issue call.
    Set by action_node. Each entry is the tool's return dict.
    """

    verification: Optional[list[dict]]
    """
    Results of get_system_status() for every system acted upon.
    Set by verify_node. Confirms whether fixes actually landed.
    """

    report: Optional[dict]
    """
    Final structured report from generate_ops_report().
    Set by report_node. This is what the API and dashboard surface.
    """

    error: Optional[str]
    """
    Set by any node that catches an unrecoverable error.
    Causes the router to skip to report_node immediately.
    """