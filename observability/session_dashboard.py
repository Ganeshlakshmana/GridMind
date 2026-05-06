"""
observability/session_dashboard.py

Reads a trace file and prints a clean CLI summary of a GridMind session.
Faster to scan than the full runner output — designed as a post-session debrief.

Usage:
    python -m observability.session_dashboard                    # latest session
    python -m observability.session_dashboard --session <id>     # specific session
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone

from observability.tracer import load_latest_trace, load_trace

# ── Terminal width ────────────────────────────────────────────────────────────
W = 64


# ── Formatting helpers ────────────────────────────────────────────────────────

def _bar(pct: float, width: int = 24) -> str:
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)


def _section(title: str) -> str:
    pad = W - len(title) - 3
    return f"\n  {title} {'━' * pad}"


def _ts(iso: str | None) -> str:
    if not iso:
        return "n/a"
    try:
        dt = datetime.fromisoformat(iso).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return iso


def _short_id(session_id: str) -> str:
    return session_id[:8] if session_id else "unknown"


def _truncate(text: str, max_len: int = W - 12) -> str:
    if not text:
        return "n/a"
    return text if len(text) <= max_len else text[:max_len] + "..."


# ── Dashboard renderer ────────────────────────────────────────────────────────

def render(trace: dict) -> None:
    session_id = trace.get("session_id", "unknown")
    elapsed    = trace.get("elapsed_seconds", "?")
    started_at = _ts(trace.get("started_at"))
    prompt     = trace.get("prompt", "n/a")
    error      = trace.get("error")

    fleet_after  = trace.get("fleet_after",  {})
    triage_plan  = trace.get("triage_plan",  {})
    actions      = trace.get("actions_taken") or []
    verification = trace.get("verification")  or []
    outcome      = trace.get("outcome",       {})

    # ── Header ────────────────────────────────────────────────────────────────
    print()
    print("╔" + "═" * (W - 2) + "╗")
    print("║" + "  GridMind — Session Dashboard".ljust(W - 2) + "║")
    print("╚" + "═" * (W - 2) + "╝")

    # ── Session metadata ──────────────────────────────────────────────────────
    print()
    print(f"  Session   {_short_id(session_id)}  │  {elapsed}s  │  {started_at}")
    print(f"  Prompt    {_truncate(prompt)}")
    print(f"  Nodes     {' → '.join(trace.get('nodes_executed', []))}")

    # ── Fleet health ──────────────────────────────────────────────────────────
    print(_section("FLEET HEALTH"))

    health   = fleet_after.get("health_score_pct",     0) or 0
    eff      = fleet_after.get("fleet_efficiency_pct", 0) or 0
    output   = fleet_after.get("total_output_kw",      0) or 0
    anomalies = fleet_after.get("anomaly_count",        0) or 0
    statuses = fleet_after.get("status_counts",        {}) or {}

    print(f"  Health    {health:5.1f}%  {_bar(health)}  efficiency {eff:.1f}%")
    print(f"  Output    {output:.2f} kW        Anomalies remaining: {anomalies}")
    status_str = "  ".join(f"{k}={v}" for k, v in sorted(statuses.items()))
    print(f"  Status    {status_str}")

    # ── Triage ────────────────────────────────────────────────────────────────
    print(_section("TRIAGE"))

    n_resolve  = len(triage_plan.get("to_resolve",  []))
    n_escalate = len(triage_plan.get("to_escalate", []))
    n_monitor  = len(triage_plan.get("to_monitor",  []))
    rationale  = triage_plan.get("rationale") or "n/a"

    print(f"  Resolved  {n_resolve}   Escalated  {n_escalate}   Monitored  {n_monitor}")
    # Word-wrap rationale at W-12 chars
    words, line = rationale.split(), ""
    prefix = "  Rationale "
    for word in words:
        if len(line) + len(word) + 1 > W - len(prefix):
            print(f"{prefix}{line}")
            prefix = "            "
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        print(f"{prefix}{line}")

    # ── Actions ───────────────────────────────────────────────────────────────
    print(_section("ACTIONS"))

    if not actions:
        print("  No actions taken this session.")
    else:
        # Group resolves by action type
        resolves: dict[str, list[str]] = defaultdict(list)
        escalates: dict[str, list[str]] = defaultdict(list)

        for a in actions:
            sid = a.get("system_id", "?")
            if a.get("type") == "resolve":
                action_name = a.get("action", "unknown")
                resolves[action_name].append(sid)
            elif a.get("type") == "escalate":
                sev = a.get("severity", "?")
                escalates[sev].append(sid)

        for action_name, sids in sorted(resolves.items()):
            ok   = all(a.get("success", True) for a in actions
                       if a.get("action") == action_name)
            mark = "✓" if ok else "✗"
            sid_display = "  ".join(sids[:3])
            extra = f"  +{len(sids)-3} more" if len(sids) > 3 else ""
            print(f"  {mark} {action_name:<28} {sid_display}{extra}")

        for severity in ("critical", "high", "medium", "low"):
            sids = escalates.get(severity, [])
            if not sids:
                continue
            sid_display = "  ".join(sids[:4])
            extra = f"  +{len(sids)-4} more" if len(sids) > 4 else ""
            print(f"  ↑ escalated ({severity:<8})         {sid_display}{extra}")

    # ── Verification ─────────────────────────────────────────────────────────
    if verification:
        print(_section("VERIFICATION"))

        total    = len(verification)
        success  = sum(1 for v in verification if v.get("fix_succeeded"))
        failed   = [v for v in verification if not v.get("fix_succeeded")]
        rate     = outcome.get("fix_success_rate_pct", 0) or 0

        print(f"  {success}/{total} fixes confirmed healthy   success rate {rate:.1f}%")

        if failed:
            print(f"\n  ✗ Fixes that did not land:")
            for v in failed:
                print(f"    {v['system_id']} — current status: {v.get('current_status', '?')}")

    # ── Escalation tickets ────────────────────────────────────────────────────
    tickets = trace.get("escalations", [])
    if tickets:
        print(_section("ESCALATION TICKETS"))
        for t in tickets:
            tid = t.get("ticket_id", "?")
            sid = t.get("system_id", "?")
            sev = t.get("severity", "?")
            rsn = _truncate(t.get("reason", ""), max_len=W - 28)
            print(f"  {tid}  {sid}  [{sev}]")
            print(f"    {rsn}")

    # ── Error ─────────────────────────────────────────────────────────────────
    if error:
        print(_section("ERROR"))
        print(f"  ⚠  {error}")

    print()
    print("─" * W)
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Display a GridMind session summary from a trace file."
    )
    parser.add_argument(
        "--session", "-s",
        type=str,
        default=None,
        help="Session ID to display. Defaults to the most recent session.",
    )
    args = parser.parse_args()

    try:
        if args.session:
            trace = load_trace(args.session)
        else:
            trace = load_latest_trace()
            if trace is None:
                print("No trace files found. Run a session first:")
                print("  python -m agent.runner \"your prompt\"")
                sys.exit(0)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    render(trace)


if __name__ == "__main__":
    main()