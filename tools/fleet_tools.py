"""
fleet_tools.py

Five read-only tools for fleet inspection.
Decorated with @tool so they work identically in:
  - LangGraph agent (Tasks 13–16)
  - MCP server       (Tasks 20–22)
  - Eval harness     (Tasks 26–28)

No writes. No side effects. Pure reads from fleet_store.
"""

from typing import Optional
from langchain_core.tools import tool

from data.fleet_store import get_system, load_fleet


# ── 1. get_system_status ──────────────────────────────────────────────────────

@tool
def get_system_status(system_id: str) -> dict:
    """
    Return the full current state of a single energy system.

    Args:
        system_id: System identifier, e.g. 'SYS_042'.

    Returns:
        Full system dict including status, output, battery, alerts, and metadata.

    Raises:
        KeyError: If system_id does not exist in the fleet.
    """
    return get_system(system_id)


# ── 2. get_fleet_summary ──────────────────────────────────────────────────────

@tool
def get_fleet_summary(status_filter: Optional[str] = None) -> dict:
    """
    Return an aggregate summary of the entire fleet, optionally filtered by status.

    Args:
        status_filter: One of 'healthy', 'degraded', 'offline', 'warning'.
                       If omitted, summarises all 50 systems.

    Returns:
        {
          "total":              int,
          "by_status":          dict[str, int],
          "avg_output_kw":      float,
          "total_output_kw":    float,
          "total_feed_in_kw":   float,
          "systems_needing_attention": list[dict],  # non-healthy systems
        }
    """
    fleet = load_fleet()

    if status_filter:
        valid = {"healthy", "degraded", "offline", "warning"}
        if status_filter not in valid:
            raise ValueError(f"Invalid status_filter '{status_filter}'. Must be one of {valid}.")
        working_set = [s for s in fleet if s["status"] == status_filter]
    else:
        working_set = fleet

    by_status: dict[str, int] = {}
    for s in fleet:                          # always count full fleet for context
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1

    outputs   = [s["solar_output_kw"] for s in working_set if s["solar_output_kw"] is not None]
    feed_ins  = [s["grid_feed_in_kw"]  for s in working_set if s["grid_feed_in_kw"]  is not None]

    avg_output   = round(sum(outputs)  / len(outputs),  2) if outputs  else 0.0
    total_output = round(sum(outputs), 2)
    total_feed   = round(sum(feed_ins), 2)

    attention = [
        {
            "system_id":   s["system_id"],
            "status":      s["status"],
            "anomaly_type": s["anomaly_type"],
            "location":    s["location"],
            "alerts":      s["alerts"],
        }
        for s in fleet
        if s["status"] != "healthy"
    ]

    return {
        "total":                     len(working_set),
        "by_status":                 by_status,
        "avg_output_kw":             avg_output,
        "total_output_kw":           total_output,
        "total_feed_in_kw":          total_feed,
        "systems_needing_attention": attention,
    }


# ── 3. detect_anomalies ───────────────────────────────────────────────────────

@tool
def detect_anomalies(
    anomaly_type: Optional[str] = None,
    threshold_pct: Optional[float] = None,
) -> dict:
    """
    Detect systems outside normal operating parameters.

    Args:
        anomaly_type:  Filter by anomaly type — one of:
                       'low_output', 'offline', 'battery_drain', 'inverter_fault'.
                       If omitted, returns all anomalous systems.
        threshold_pct: Float 0–100. If provided, also flag any system whose
                       solar_output_kw is below this percentage of expected_output_kw,
                       regardless of stored anomaly_type.

    Returns:
        {
          "total_anomalies": int,
          "anomalies": list[dict],   # one entry per affected system
        }
    """
    fleet = load_fleet()

    valid_types = {"low_output", "offline", "battery_drain", "inverter_fault"}
    if anomaly_type and anomaly_type not in valid_types:
        raise ValueError(f"Invalid anomaly_type '{anomaly_type}'. Must be one of {valid_types}.")

    results = []

    for s in fleet:
        flagged      = False
        flag_reason  = None

        # Filter by stored anomaly label
        if anomaly_type:
            if s["anomaly_type"] == anomaly_type:
                flagged     = True
                flag_reason = anomaly_type
        else:
            if s["anomaly_type"] is not None:
                flagged     = True
                flag_reason = s["anomaly_type"]

        # Additional threshold check — catches degraded systems not yet labeled
        if threshold_pct is not None and s["expected_output_kw"] and s["expected_output_kw"] > 0:
            actual_pct = (s["solar_output_kw"] / s["expected_output_kw"]) * 100
            if actual_pct < threshold_pct:
                flagged     = True
                flag_reason = flag_reason or f"output below {threshold_pct}%"

        if flagged:
            results.append({
                "system_id":          s["system_id"],
                "location":           s["location"],
                "status":             s["status"],
                "anomaly_type":       s["anomaly_type"],
                "flag_reason":        flag_reason,
                "solar_output_kw":    s["solar_output_kw"],
                "expected_output_kw": s["expected_output_kw"],
                "battery_soc_pct":    s["battery_soc_pct"],
                "alerts":             s["alerts"],
                "last_updated":       s["last_updated"],
            })

    return {
        "total_anomalies": len(results),
        "anomalies":       results,
    }


# ── 4. get_system_history ─────────────────────────────────────────────────────

@tool
def get_system_history(system_id: str, hours_back: int = 24) -> dict:
    """
    Return recent hourly readings for a system.

    Args:
        system_id:  System identifier, e.g. 'SYS_019'.
        hours_back: Number of hours of history to return (1–24). Defaults to 24.

    Returns:
        {
          "system_id":  str,
          "anomaly_type": str | None,
          "hours_back": int,
          "readings":   list[dict],   # oldest first
        }
    """
    if not 1 <= hours_back <= 24:
        raise ValueError(f"hours_back must be between 1 and 24, got {hours_back}.")

    system  = get_system(system_id)
    history = system.get("history", [])
    slice_  = history[-hours_back:] if len(history) >= hours_back else history

    return {
        "system_id":    system_id,
        "anomaly_type": system["anomaly_type"],
        "hours_back":   hours_back,
        "readings":     slice_,
    }


# ── 5. compare_systems ────────────────────────────────────────────────────────

@tool
def compare_systems(system_ids: list[str]) -> dict:
    """
    Return a side-by-side comparison of key metrics for multiple systems.

    Args:
        system_ids: List of system IDs to compare, e.g. ['SYS_001', 'SYS_042'].
                    Must contain at least 2 IDs, maximum 10.

    Returns:
        {
          "systems": list[dict],   # one compact metric dict per system
          "comparison_notes": list[str],  # auto-generated observations
        }
    """
    if len(system_ids) < 2:
        raise ValueError("compare_systems requires at least 2 system IDs.")
    if len(system_ids) > 10:
        raise ValueError("compare_systems accepts a maximum of 10 system IDs.")

    systems = [get_system(sid) for sid in system_ids]

    rows = []
    for s in systems:
        exp = s["expected_output_kw"] or 0
        out = s["solar_output_kw"]    or 0
        efficiency_pct = round((out / exp) * 100, 1) if exp > 0 else None

        rows.append({
            "system_id":          s["system_id"],
            "location":           s["location"],
            "system_type":        s["system_type"],
            "status":             s["status"],
            "anomaly_type":       s["anomaly_type"],
            "solar_output_kw":    s["solar_output_kw"],
            "expected_output_kw": s["expected_output_kw"],
            "efficiency_pct":     efficiency_pct,
            "battery_soc_pct":    s["battery_soc_pct"],
            "grid_feed_in_kw":    s["grid_feed_in_kw"],
            "alerts":             s["alerts"],
        })

    # Auto-generate observations the agent can include in its report
    notes = []

    statuses = {r["status"] for r in rows}
    if len(statuses) > 1:
        notes.append(f"Mixed statuses detected: {', '.join(sorted(statuses))}.")

    efficiencies = [(r["system_id"], r["efficiency_pct"]) for r in rows if r["efficiency_pct"] is not None]
    if efficiencies:
        best  = max(efficiencies, key=lambda x: x[1])
        worst = min(efficiencies, key=lambda x: x[1])
        if best[0] != worst[0]:
            notes.append(
                f"{best[0]} has the highest efficiency at {best[1]}%; "
                f"{worst[0]} the lowest at {worst[1]}%."
            )

    low_battery = [r["system_id"] for r in rows if r["battery_soc_pct"] is not None and r["battery_soc_pct"] < 20]
    if low_battery:
        notes.append(f"Low battery SOC (<20%) on: {', '.join(low_battery)}.")

    return {
        "systems":           rows,
        "comparison_notes":  notes,
    }