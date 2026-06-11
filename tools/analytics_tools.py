"""
analytics_tools.py

Two read-only analytics tools for trend analysis and operational reporting.
Decorated with @tool — works identically in LangGraph agent and MCP server.

These tools are the agent's "intelligence layer" — they transform raw fleet
data into structured insights the agent can narrate into natural language.
"""

from typing import Optional
from langchain_core.tools import tool

from data.fleet_store import load_escalations, load_fleet

# ── Constants ─────────────────────────────────────────────────────────────────

_VALID_METRICS = {
    "solar_output_kw",
    "expected_output_kw",
    "battery_soc_pct",
    "grid_feed_in_kw",
}

_ALL_SECTIONS = {
    "executive_summary",
    "anomaly_breakdown",
    "resolution_log",
    "escalations",
    "recommendations",
}


# ── 1. get_fleet_trends ───────────────────────────────────────────────────────

@tool
def get_fleet_trends(
    hours_back: int = 24,
    metric: str = "solar_output_kw",
) -> dict:
    """
    Aggregate a chosen metric hour-by-hour across the entire fleet history.

    Use this to answer questions like:
      - "Has total output been declining over the last 12 hours?"
      - "When did most anomalies appear today?"
      - "What is the average battery SOC trend?"

    Args:
        hours_back: Number of hours to analyse (1–24). Defaults to 24.
        metric:     One of:
                      'solar_output_kw'    (default)
                      'expected_output_kw'
                      'battery_soc_pct'
                      'grid_feed_in_kw'

    Returns:
        {
          "metric":       str,
          "hours_back":   int,
          "series": [
            {
              "hour_index":    int,       # 0 = oldest, hours_back-1 = most recent
              "timestamp":     str,       # ISO from first system with a reading
              "avg":           float,     # fleet average for this hour (nulls excluded)
              "total":         float,     # fleet total for this hour
              "reporting":     int,       # systems with a non-null reading
              "healthy_count": int,       # systems with status='healthy' this hour
              "anomaly_count": int,       # systems with non-null status != 'healthy'
            },
            ...
          ],
          "summary": {
            "peak_hour_index":   int,
            "peak_value":        float,
            "trough_hour_index": int,
            "trough_value":      float,
            "overall_trend":     str,    # 'improving' | 'declining' | 'stable'
          }
        }
    """
    if not 1 <= hours_back <= 24:
        raise ValueError(f"hours_back must be between 1 and 24, got {hours_back}.")
    if metric not in _VALID_METRICS:
        raise ValueError(
            f"Invalid metric '{metric}'. "
            f"Valid metrics: {sorted(_VALID_METRICS)}."
        )

    try:
        from db.bigquery_client import get_bq_client, sync_json_to_duckdb
        sync_json_to_duckdb()
        client = get_bq_client()
        
        # Get the distinct timestamps of the latest hours_back readings
        # to filter the query correctly
        query_str = f"""
            WITH latest_timestamps AS (
                SELECT DISTINCT timestamp 
                FROM telemetry 
                ORDER BY timestamp DESC 
                LIMIT {hours_back}
            )
            SELECT
                timestamp,
                AVG({metric}) as avg_val,
                SUM({metric}) as total_val,
                COUNT({metric}) as reporting_cnt,
                SUM(CASE WHEN status = 'healthy' THEN 1 ELSE 0 END) as healthy_cnt,
                SUM(CASE WHEN status != 'healthy' AND status IS NOT NULL THEN 1 ELSE 0 END) as anomaly_cnt
            FROM telemetry
            WHERE timestamp IN (SELECT timestamp FROM latest_timestamps)
            GROUP BY timestamp
            ORDER BY timestamp ASC
        """
        rows = client.query(query_str).result()
        series = []
        for hour_idx, r in enumerate(rows):
            ts = r["timestamp"]
            ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            
            avg = round(float(r["avg_val"]), 2) if r["avg_val"] is not None else 0.0
            total = round(float(r["total_val"]), 2) if r["total_val"] is not None else 0.0
            
            series.append({
                "hour_index":    hour_idx,
                "timestamp":     ts_str,
                "avg":           avg,
                "total":         total,
                "reporting":     int(r["reporting_cnt"]),
                "healthy_count": int(r["healthy_cnt"]),
                "anomaly_count": int(r["anomaly_cnt"]),
            })
    except Exception as exc:
        # Fallback to local JSON array loop
        fleet  = load_fleet()
        series = []

        for hour_idx in range(hours_back):
            offset = -hours_back + hour_idx

            values        = []
            healthy_count = 0
            anomaly_count = 0
            timestamp     = None

            for system in fleet:
                history = system.get("history", [])
                if len(history) < hours_back:
                    continue

                reading = history[offset]
                if timestamp is None and reading.get("timestamp"):
                    timestamp = reading["timestamp"]

                val = reading.get(metric)

                if metric == "battery_soc_pct" and system["system_type"] == "solar_only":
                    continue

                if val is not None:
                    values.append(val)

                status = reading.get("status")
                if status == "healthy":
                    healthy_count += 1
                elif status is not None:
                    anomaly_count += 1

            avg   = round(sum(values) / len(values), 2) if values else 0.0
            total = round(sum(values), 2)

            series.append({
                "hour_index":    hour_idx,
                "timestamp":     timestamp,
                "avg":           avg,
                "total":         total,
                "reporting":     len(values),
                "healthy_count": healthy_count,
                "anomaly_count": anomaly_count,
            })

    # ── Summary statistics ────────────────────────────────────────────────────
    avgs = [pt["avg"] for pt in series if pt["avg"] is not None]

    if avgs:
        peak_idx   = max(range(len(avgs)), key=lambda i: avgs[i])
        trough_idx = min(range(len(avgs)), key=lambda i: avgs[i])

        # Trend: compare first third vs last third of the window
        third = max(len(avgs) // 3, 1)
        early_avg = sum(avgs[:third])  / third
        late_avg  = sum(avgs[-third:]) / third
        delta_pct = ((late_avg - early_avg) / early_avg * 100) if early_avg > 0 else 0

        if delta_pct > 5:
            trend = "improving"
        elif delta_pct < -5:
            trend = "declining"
        else:
            trend = "stable"

        summary = {
            "peak_hour_index":   peak_idx,
            "peak_value":        avgs[peak_idx],
            "trough_hour_index": trough_idx,
            "trough_value":      avgs[trough_idx],
            "overall_trend":     trend,
        }
    else:
        summary = {
            "peak_hour_index":   None,
            "peak_value":        None,
            "trough_hour_index": None,
            "trough_value":      None,
            "overall_trend":     "no_data",
        }

    return {
        "metric":     metric,
        "hours_back": hours_back,
        "series":     series,
        "summary":    summary,
    }


# ── 2. generate_ops_report ────────────────────────────────────────────────────

@tool
def generate_ops_report(
    include_sections: Optional[list[str]] = None,
) -> dict:
    """
    Generate a structured operational report of the current fleet state.

    Sections are modular — request a subset for a quick brief, or omit
    include_sections to get the full report.

    Args:
        include_sections: List of section names to include. Defaults to all.
                          Valid sections:
                            'executive_summary'  — health score, totals, KPIs
                            'anomaly_breakdown'  — per-system anomaly details
                            'resolution_log'     — actions taken this session
                            'escalations'        — open human-intervention tickets
                            'recommendations'    — suggested next actions

    Returns:
        Dict with requested sections as top-level keys, plus a 'generated_at' timestamp.

    Raises:
        ValueError: If any requested section name is invalid.
    """
    if include_sections is None:
        sections = _ALL_SECTIONS
    else:
        invalid = set(include_sections) - _ALL_SECTIONS
        if invalid:
            raise ValueError(
                f"Invalid sections: {invalid}. "
                f"Valid sections: {sorted(_ALL_SECTIONS)}."
            )
        sections = set(include_sections)

    fleet       = load_fleet()
    escalations = load_escalations()
    report: dict = {}

    # ── executive_summary ─────────────────────────────────────────────────────
    if "executive_summary" in sections:
        status_counts: dict[str, int] = {}
        for s in fleet:
            status_counts[s["status"]] = status_counts.get(s["status"], 0) + 1

        outputs  = [s["solar_output_kw"]   for s in fleet if s["solar_output_kw"]   is not None]
        expected = [s["expected_output_kw"] for s in fleet if s["expected_output_kw"] is not None]
        feed_ins = [s["grid_feed_in_kw"]    for s in fleet if s["grid_feed_in_kw"]    is not None]

        total_output   = round(sum(outputs), 2)
        total_expected = round(sum(expected), 2)
        fleet_efficiency = (
            round(total_output / total_expected * 100, 1)
            if total_expected > 0 else 0.0
        )

        healthy_count = status_counts.get("healthy", 0)
        health_score  = round(healthy_count / len(fleet) * 100, 1)

        open_escalations = sum(1 for e in escalations if e.get("status") == "open")

        report["executive_summary"] = {
            "fleet_size":          len(fleet),
            "health_score_pct":    health_score,
            "status_counts":       status_counts,
            "total_output_kw":     total_output,
            "total_expected_kw":   total_expected,
            "fleet_efficiency_pct": fleet_efficiency,
            "total_feed_in_kw":    round(sum(feed_ins), 2),
            "open_escalations":    open_escalations,
            "anomaly_count":       len(fleet) - healthy_count,
        }

    # ── anomaly_breakdown ─────────────────────────────────────────────────────
    if "anomaly_breakdown" in sections:
        anomalies = []
        for s in fleet:
            if s["anomaly_type"] is None:
                continue

            exp = s["expected_output_kw"] or 0
            out = s["solar_output_kw"]    or 0
            efficiency_pct = round(out / exp * 100, 1) if exp > 0 else None

            anomalies.append({
                "system_id":          s["system_id"],
                "location":           s["location"],
                "system_type":        s["system_type"],
                "status":             s["status"],
                "anomaly_type":       s["anomaly_type"],
                "solar_output_kw":    s["solar_output_kw"],
                "expected_output_kw": s["expected_output_kw"],
                "efficiency_pct":     efficiency_pct,
                "battery_soc_pct":    s["battery_soc_pct"],
                "alerts":             s["alerts"],
                "last_updated":       s["last_updated"],
            })

        # Sort by severity: offline first, then degraded, warning, then by system_id
        severity_order = {"offline": 0, "degraded": 1, "warning": 2, "healthy": 3}
        anomalies.sort(key=lambda x: (severity_order.get(x["status"], 9), x["system_id"]))

        report["anomaly_breakdown"] = {
            "total": len(anomalies),
            "items": anomalies,
        }

    # ── resolution_log ────────────────────────────────────────────────────────
    if "resolution_log" in sections:
        resolved = []
        for s in fleet:
            action_entries = [
                a for a in s.get("alerts", [])
                if "ACTION '" in a or "ESCALATED" in a
            ]
            if action_entries:
                resolved.append({
                    "system_id":    s["system_id"],
                    "current_status": s["status"],
                    "audit_trail":  action_entries,
                })

        report["resolution_log"] = {
            "total_actions": sum(len(r["audit_trail"]) for r in resolved),
            "systems_touched": len(resolved),
            "items": resolved,
        }

    # ── escalations ───────────────────────────────────────────────────────────
    if "escalations" in sections:
        open_tickets = [e for e in escalations if e.get("status") == "open"]
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        open_tickets.sort(key=lambda x: severity_order.get(x.get("severity", "low"), 9))

        report["escalations"] = {
            "total_open": len(open_tickets),
            "tickets":    open_tickets,
        }

    # ── recommendations ───────────────────────────────────────────────────────
    if "recommendations" in sections:
        recs = []
        for s in fleet:
            match s["anomaly_type"]:
                case "inverter_fault":
                    recs.append({
                        "system_id":   s["system_id"],
                        "priority":    "high",
                        "action":      "restart_inverter",
                        "reason":      f"{s['system_id']} has zero output due to inverter fault.",
                    })
                case "offline":
                    recs.append({
                        "system_id":   s["system_id"],
                        "priority":    "high",
                        "action":      "force_reconnect or escalate_issue",
                        "reason":      f"{s['system_id']} has been offline since {s['last_updated']}.",
                    })
                case "battery_drain":
                    soc = s.get("battery_soc_pct")
                    priority = "critical" if soc and soc < 15 else "medium"
                    recs.append({
                        "system_id":   s["system_id"],
                        "priority":    priority,
                        "action":      "reset_battery_management",
                        "reason":      f"{s['system_id']} battery SOC at {soc}%, draining faster than expected.",
                    })
                case "low_output":
                    recs.append({
                        "system_id":   s["system_id"],
                        "priority":    "medium",
                        "action":      "clear_low_output_flag after manual inspection",
                        "reason":      f"{s['system_id']} output below 50% of expected.",
                    })

        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        recs.sort(key=lambda x: priority_order.get(x["priority"], 9))

        report["recommendations"] = {
            "total": len(recs),
            "items": recs,
        }

    from datetime import datetime, timezone
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["sections_included"] = sorted(sections)

    return report