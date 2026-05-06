"""
observability/tracer.py

Writes a structured JSON trace file to traces/ after every agent session.
Called by runner.py — completely decoupled from the LangGraph graph.

Trace files are the source of truth for:
  - Eval harness (Tasks 26–28): compares actual vs expected tool sequences
  - Session dashboard (Task 19): reads the latest trace to render summary
  - Post-mortem debugging: full audit trail of every decision and action

Usage:
    from observability.tracer import trace_session
    trace_session(report)   # report is the dict returned by run_session()
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TRACES_DIR = Path(__file__).parent.parent / "traces"


def trace_session(report: dict) -> Path:
    """
    Extract observability data from the final report and write it to
    traces/session_<session_id>.json.

    Args:
        report: The dict returned by agent.runner.run_session().

    Returns:
        Path to the written trace file.
    """
    TRACES_DIR.mkdir(exist_ok=True)

    session    = report.get("session", {})
    session_id = session.get("session_id", "unknown")

    # ── Fleet before / after ──────────────────────────────────────────────────
    # "before" is reconstructed from the triage input (anomalies detected
    # before any actions). "after" is the executive summary post-actions.
    ex           = report.get("executive_summary", {})
    actions      = session.get("actions_taken") or []
    verification = session.get("verification")  or []
    triage_plan  = session.get("triage_plan")   or {}

    resolved_count  = sum(1 for a in actions   if a.get("type") == "resolve")
    escalated_count = sum(1 for a in actions   if a.get("type") == "escalate")
    verified_count  = sum(1 for v in verification if v.get("fix_succeeded"))

    fix_success_rate = (
        round(verified_count / resolved_count * 100, 1)
        if resolved_count > 0 else None
    )

    # Infer nodes executed from which state fields are populated
    nodes_executed = ["monitor_node", "detect_node"]
    if triage_plan:
        nodes_executed.append("triage_node")
    if actions:
        nodes_executed.append("action_node")
    if verification:
        nodes_executed.append("verify_node")
    nodes_executed.append("report_node")

    # ── Escalation tickets written this session ───────────────────────────────
    escalation_tickets = [
        {
            "ticket_id": a.get("ticket_id"),
            "system_id": a.get("system_id"),
            "severity":  a.get("severity"),
            "reason":    a.get("reason"),
        }
        for a in actions
        if a.get("type") == "escalate" and not a.get("error")
    ]

    # ── Assemble trace ────────────────────────────────────────────────────────
    trace = {
        "session_id":      session_id,
        "started_at":      session.get("started_at"),
        "elapsed_seconds": session.get("elapsed_seconds"),
        "prompt":          session.get("prompt"),
        "nodes_executed":  nodes_executed,
        "fleet_after": {
            "health_score_pct":    ex.get("health_score_pct"),
            "anomaly_count":       ex.get("anomaly_count"),
            "status_counts":       ex.get("status_counts"),
            "fleet_efficiency_pct": ex.get("fleet_efficiency_pct"),
            "total_output_kw":     ex.get("total_output_kw"),
        },
        "triage_plan": {
            "rationale":    triage_plan.get("rationale"),
            "to_resolve":   triage_plan.get("to_resolve",  []),
            "to_escalate":  triage_plan.get("to_escalate", []),
            "to_monitor":   triage_plan.get("to_monitor",  []),
        },
        "actions_taken":  actions,
        "verification":   verification,
        "escalations":    escalation_tickets,
        "outcome": {
            "systems_resolved":   resolved_count,
            "systems_escalated":  escalated_count,
            "fixes_verified":     verified_count,
            "fix_success_rate_pct": fix_success_rate,
        },
        "error": session.get("error") or report.get("error"),
        "traced_at": datetime.now(timezone.utc).isoformat(),
    }

    out_path = TRACES_DIR / f"session_{session_id}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(trace, f, indent=2, ensure_ascii=False)

    logger.info("Trace written → %s", out_path)
    return out_path


def load_latest_trace() -> dict | None:
    """
    Load the most recently written trace file.
    Used by session_dashboard.py to render the last session summary.
    Returns None if no traces exist yet.
    """
    if not TRACES_DIR.exists():
        return None

    trace_files = sorted(TRACES_DIR.glob("session_*.json"), key=lambda p: p.stat().st_mtime)
    if not trace_files:
        return None

    with open(trace_files[-1], encoding="utf-8") as f:
        return json.load(f)


def load_trace(session_id: str) -> dict:
    """
    Load a specific trace by session_id.
    Used by the eval harness to inspect individual scenario runs.

    Raises:
        FileNotFoundError: If no trace exists for the given session_id.
    """
    path = TRACES_DIR / f"session_{session_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"No trace found for session '{session_id}' at {path}.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)