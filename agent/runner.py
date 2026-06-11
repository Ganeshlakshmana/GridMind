"""
agent/runner.py

Public entrypoint for the GridMind agent.
Accepts a natural language prompt, runs the compiled graph,
and returns the final report dict.

Used by:
    api/main.py          — POST /run  endpoint
    CLI                  — python -m agent.runner "your prompt"
    evals/runner.py      — each scenario calls run_session()

Usage:
    from agent.runner import run_session

    report = run_session("Run a full fleet diagnostic and fix what you can.")
    print(report["executive_summary"])
"""

import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

# Fix OpenMP conflict between PyTorch and FAISS on Windows
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from dotenv import load_dotenv

from agent.graph import graph
from observability.tracer import trace_session
from agent.state import VPPState

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_session(prompt: str, session_id: str | None = None) -> dict:
    """
    Run a complete GridMind agent session.

    Args:
        prompt:     Natural language operator request.
        session_id: Optional — provide for reproducible tracing.
                    Auto-generated UUID if omitted.

    Returns:
        The final report dict from report_node, including:
            executive_summary, anomaly_breakdown, resolution_log,
            escalations, recommendations, session metadata.
    """
    sid   = session_id or str(uuid.uuid4())
    start = datetime.now(timezone.utc)

    logger.info("Session %s started", sid)
    logger.info("Prompt: %s", prompt)

    initial_state: VPPState = {
        "prompt":        prompt,
        "session_id":    sid,
        "messages":      [],
        "fleet_summary": None,
        "anomalies":     None,
        "triage_plan":   None,
        "actions_taken": None,
        "verification":  None,
        "report":        None,
        "error":         None,
    }

    try:
        final_state = graph.invoke(initial_state)
    except Exception as exc:
        logger.error("Graph invocation failed: %s", exc)
        return {
            "error":      str(exc),
            "session_id": sid,
            "prompt":     prompt,
        }

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    report  = final_state.get("report", {})

    # Attach timing to session metadata
    if "session" in report:
        report["session"]["elapsed_seconds"] = round(elapsed, 2)
        report["session"]["started_at"]      = start.isoformat()

    trace_session(report)

    logger.info(
        "Session %s completed in %.1fs | health=%.1f%% | actions=%d",
        sid,
        elapsed,
        report.get("executive_summary", {}).get("health_score_pct", 0),
        len(report.get("session", {}).get("actions_taken") or []),
    )

    return report


# ── CLI entrypoint ────────────────────────────────────────────────────────────

def _print_report(report: dict) -> None:
    """Pretty-print the report to stdout for CLI use."""
    print("\n" + "═" * 64)
    print("  GridMind Session Report")
    print("═" * 64)

    session = report.get("session", {})
    print(f"  Session ID : {session.get('session_id', 'n/a')}")
    print(f"  Prompt     : {session.get('prompt', 'n/a')}")
    print(f"  Elapsed    : {session.get('elapsed_seconds', '?')}s")
    print(f"  Started    : {session.get('started_at', 'n/a')}")

    ex = report.get("executive_summary", {})
    if ex:
        print("\n── Executive Summary ──────────────────────────────────────")
        print(f"  Fleet size       : {ex.get('fleet_size')}")
        print(f"  Health score     : {ex.get('health_score_pct')}%")
        print(f"  Fleet efficiency : {ex.get('fleet_efficiency_pct')}%")
        print(f"  Total output     : {ex.get('total_output_kw')} kW")
        print(f"  Anomalies        : {ex.get('anomaly_count')}")
        print(f"  Open escalations : {ex.get('open_escalations')}")
        print(f"  Status counts    : {ex.get('status_counts')}")

    triage = session.get("triage_plan", {})
    if triage:
        print("\n── Triage Plan ────────────────────────────────────────────")
        print(f"  Rationale  : {triage.get('rationale')}")
        print(f"  To resolve : {len(triage.get('to_resolve', []))}")
        print(f"  To escalate: {len(triage.get('to_escalate', []))}")
        print(f"  To monitor : {len(triage.get('to_monitor', []))}")

    actions = session.get("actions_taken", [])
    if actions:
        print("\n── Actions Taken ───────────────────────────────────────────")
        for a in actions:
            sid_  = a.get("system_id")
            kind  = a.get("type", "?")
            ok    = a.get("success", a.get("status", "?"))
            print(f"  [{kind:9}] {sid_} → {ok}")

    verification = session.get("verification", [])
    if verification:
        print("\n── Verification ────────────────────────────────────────────")
        for v in verification:
            mark = "OK" if v.get("fix_succeeded") else "NOT OK"
            print(f"  {mark} {v['system_id']} — {v['current_status']}")

    recs = report.get("recommendations", {}).get("items", [])
    if recs:
        print("\n── Recommendations ─────────────────────────────────────────")
        for r in recs[:5]:
            print(f"  [{r['priority']:8}] {r['system_id']} → {r['action']}")
        if len(recs) > 5:
            print(f"  ... and {len(recs) - 5} more")

    error = report.get("error") or session.get("error")
    if error:
        print(f"\n   Error: {error}")

    print("═" * 64 + "\n")


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "Run a full fleet diagnostic. Resolve any issues you can automatically "
        "and escalate anything that requires human intervention."
    )
    report = run_session(prompt)
    _print_report(report)