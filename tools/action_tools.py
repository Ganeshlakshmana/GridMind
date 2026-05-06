"""
action_tools.py

Three write-side tools that mutate fleet state.
Decorated with @tool — works identically in LangGraph agent and MCP server.

All writes go through fleet_store — never direct file I/O.
Every action appends an audit entry to system['alerts'] for traceability.
"""

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from langchain_core.tools import tool

from data.fleet_store import get_system, save_escalation, update_system

# ── Allowed actions and their target anomaly types ────────────────────────────

_ACTION_ANOMALY_MAP: dict[str, set[str | None]] = {
    "restart_inverter":         {"inverter_fault"},
    "reset_battery_management": {"battery_drain"},
    "clear_low_output_flag":    {"low_output"},
    "force_reconnect":          {"offline"},
}

_VALID_ACTIONS     = set(_ACTION_ANOMALY_MAP)
_VALID_SEVERITIES  = {"low", "medium", "high", "critical"}

# Fields a technician may update via update_system_config.
# Excludes history, alerts, status, anomaly_type — those are agent/store territory.
_CONFIG_WHITELIST = {
    "location",
    "system_type",
    "solar_capacity_kw",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(system_id: str, action: str, notes: str) -> str:
    return f"[{_now_iso()}] ACTION '{action}' applied to {system_id}. Notes: {notes}"


# ── 1. resolve_issue ──────────────────────────────────────────────────────────

@tool
def resolve_issue(
    system_id: str,
    action: str,
    notes: Optional[str] = "",
) -> dict:
    """
    Apply a remediation action to a system and update its status in fleet.json.

    Args:
        system_id: System to fix, e.g. 'SYS_019'.
        action:    One of:
                     'restart_inverter'         — clears inverter_fault
                     'reset_battery_management' — clears battery_drain
                     'clear_low_output_flag'    — clears low_output after inspection
                     'force_reconnect'          — attempts to bring offline system online
        notes:     Optional free-text note logged in the system's audit trail.

    Returns:
        {
          "system_id":    str,
          "action":       str,
          "previous_status":  str,
          "new_status":   str,
          "previous_anomaly": str | None,
          "new_anomaly":  None,
          "audit_entry":  str,
          "success":      bool,
        }

    Raises:
        KeyError:   If system_id does not exist.
        ValueError: If action is invalid or mismatched to the system's anomaly.
    """
    if action not in _VALID_ACTIONS:
        raise ValueError(
            f"Invalid action '{action}'. "
            f"Valid actions: {sorted(_VALID_ACTIONS)}."
        )

    system = get_system(system_id)
    current_anomaly = system["anomaly_type"]
    current_status  = system["status"]

    allowed_anomalies = _ACTION_ANOMALY_MAP[action]
    if current_anomaly not in allowed_anomalies:
        raise ValueError(
            f"Action '{action}' is not applicable to a system with "
            f"anomaly_type='{current_anomaly}'. "
            f"This action targets: {sorted(str(a) for a in allowed_anomalies)}."
        )

    # Determine resulting state per action
    match action:
        case "restart_inverter":
            new_status  = "healthy"
            new_anomaly = None
            new_output  = round(system["solar_capacity_kw"] * 0.80, 2)
            extra_fields = {
                "solar_output_kw":  new_output,
                "grid_feed_in_kw":  round(new_output * 0.50, 2),
            }

        case "reset_battery_management":
            new_status   = "healthy"
            new_anomaly  = None
            extra_fields = {
                "battery_soc_pct": 65.0,   # safe default post-reset
            }

        case "clear_low_output_flag":
            new_status   = "healthy"
            new_anomaly  = None
            extra_fields = {}

        case "force_reconnect":
            # Reconnect succeeds 80% of the time in simulation
            import random
            success = random.random() < 0.80
            if success:
                new_status   = "healthy"
                new_anomaly  = None
                new_output   = round(system["solar_capacity_kw"] * 0.75, 2)
                extra_fields = {
                    "solar_output_kw": new_output,
                    "grid_feed_in_kw": round(new_output * 0.45, 2),
                }
            else:
                # Still offline — log the attempt but don't change status
                audit_entry = _audit(system_id, action, f"Reconnect attempt FAILED. {notes}")
                existing_alerts = system["alerts"] + [audit_entry]
                update_system(system_id, {"alerts": existing_alerts})
                return {
                    "system_id":        system_id,
                    "action":           action,
                    "previous_status":  current_status,
                    "new_status":       current_status,
                    "previous_anomaly": current_anomaly,
                    "new_anomaly":      current_anomaly,
                    "audit_entry":      audit_entry,
                    "success":          False,
                }

        case _:
            raise ValueError(f"Unhandled action '{action}'.")   # should never reach

    audit_entry = _audit(system_id, action, notes or "No additional notes.")

    update_system(
        system_id,
        {
            "status":       new_status,
            "anomaly_type": new_anomaly,
            "alerts":       system["alerts"] + [audit_entry],
            **extra_fields,
        },
    )

    return {
        "system_id":        system_id,
        "action":           action,
        "previous_status":  current_status,
        "new_status":       new_status,
        "previous_anomaly": current_anomaly,
        "new_anomaly":      new_anomaly,
        "audit_entry":      audit_entry,
        "success":          True,
    }


# ── 2. escalate_issue ─────────────────────────────────────────────────────────

@tool
def escalate_issue(
    system_id: str,
    reason: str,
    severity: str,
) -> dict:
    """
    Raise a human-intervention ticket for a system and persist it to escalations.json.

    Use this when automated resolution is not possible or has already failed.

    Args:
        system_id: System requiring human attention, e.g. 'SYS_004'.
        reason:    Clear description of why escalation is needed.
        severity:  One of 'low', 'medium', 'high', 'critical'.

    Returns:
        {
          "ticket_id":  str,   # ESC_<uuid4 short>
          "system_id":  str,
          "reason":     str,
          "severity":   str,
          "created_at": str,
          "status":     "open",
        }

    Raises:
        KeyError:   If system_id does not exist.
        ValueError: If severity is not a valid level.
    """
    if severity not in _VALID_SEVERITIES:
        raise ValueError(
            f"Invalid severity '{severity}'. "
            f"Must be one of: {sorted(_VALID_SEVERITIES)}."
        )

    # Validate system exists
    system = get_system(system_id)

    ticket_id  = f"ESC_{uuid.uuid4().hex[:8].upper()}"
    created_at = _now_iso()

    ticket = {
        "ticket_id":  ticket_id,
        "system_id":  system_id,
        "reason":     reason,
        "severity":   severity,
        "created_at": created_at,
        "status":     "open",
    }

    save_escalation(ticket)

    # Also append escalation notice to system's alert log
    audit_entry = (
        f"[{created_at}] ESCALATED — ticket {ticket_id} "
        f"(severity={severity}). Reason: {reason}"
    )
    update_system(system_id, {"alerts": system["alerts"] + [audit_entry]})

    return ticket


# ── 3. update_system_config ───────────────────────────────────────────────────

@tool
def update_system_config(system_id: str, config_fields: dict) -> dict:
    """
    Update physical/configuration fields for a system after field work.

    Restricted to a safe whitelist — cannot overwrite status, anomaly_type,
    history, or alerts. Use resolve_issue to change operational state.

    Args:
        system_id:     System to update, e.g. 'SYS_007'.
        config_fields: Dict of fields to update. Allowed keys:
                         'location'          — string
                         'system_type'       — 'solar_only' | 'solar+battery' | 'solar+battery+ev'
                         'solar_capacity_kw' — float > 0

    Returns:
        Updated system dict.

    Raises:
        KeyError:   If system_id does not exist.
        ValueError: If any key is outside the whitelist or values are invalid.
    """
    if not config_fields:
        raise ValueError("config_fields must not be empty.")

    disallowed = set(config_fields) - _CONFIG_WHITELIST
    if disallowed:
        raise ValueError(
            f"Fields {disallowed} are not configurable via update_system_config. "
            f"Allowed fields: {sorted(_CONFIG_WHITELIST)}."
        )

    # Field-level validation
    if "solar_capacity_kw" in config_fields:
        val = config_fields["solar_capacity_kw"]
        if not isinstance(val, (int, float)) or val <= 0:
            raise ValueError(f"solar_capacity_kw must be a positive number, got {val!r}.")

    if "system_type" in config_fields:
        valid_types = {"solar_only", "solar+battery", "solar+battery+ev"}
        if config_fields["system_type"] not in valid_types:
            raise ValueError(
                f"Invalid system_type '{config_fields['system_type']}'. "
                f"Must be one of: {valid_types}."
            )

    return update_system(system_id, config_fields)