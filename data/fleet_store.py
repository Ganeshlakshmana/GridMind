"""
fleet_store.py

Single point of contact between the application and disk.
Every tool, agent node, and API endpoint reads/writes fleet data through here.
Nothing else in the codebase should open fleet.json directly.

Public API:
    load_fleet()                        -> list[dict]
    save_fleet(fleet)                   -> None
    get_system(system_id)               -> dict          raises KeyError
    update_system(system_id, fields)    -> dict          raises KeyError
    load_escalations()                  -> list[dict]
    save_escalation(ticket)             -> None
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────

_DATA_DIR        = Path(__file__).parent
FLEET_PATH       = _DATA_DIR / "fleet.json"
ESCALATIONS_PATH = _DATA_DIR / "escalations.json"

# ── In-memory cache ───────────────────────────────────────────────────────────
# Avoids repeated disk reads during a single agent run (5–10 tool calls).
# Invalidated on every save so reads always reflect the latest written state.

_fleet_cache: list[dict] | None = None


# ── Fleet ─────────────────────────────────────────────────────────────────────

def load_fleet(force: bool = False) -> list[dict]:
    """
    Load and return the full fleet from disk.
    Results are cached after the first read. Pass force=True to bypass cache.
    """
    global _fleet_cache
    if _fleet_cache is not None and not force:
        return _fleet_cache

    if not FLEET_PATH.exists():
        raise FileNotFoundError(
            f"fleet.json not found at {FLEET_PATH}. "
            "Run `python -m data.generate_fleet` first."
        )

    with open(FLEET_PATH, encoding="utf-8") as f:
        _fleet_cache = json.load(f)

    return _fleet_cache


def save_fleet(fleet: list[dict]) -> None:
    """
    Write fleet to disk atomically (write to .tmp, then rename).
    Invalidates the in-memory cache so the next load_fleet() reads fresh data.
    """
    global _fleet_cache

    tmp_path = FLEET_PATH.with_suffix(".tmp.json")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(fleet, f, indent=2, ensure_ascii=False)

    # os.replace is atomic on POSIX; on Windows it is not fully atomic but
    # still safer than writing directly to the target file.
    os.replace(tmp_path, FLEET_PATH)

    _fleet_cache = fleet   # update cache to the version just written


def get_system(system_id: str) -> dict:
    """
    Return the system dict for system_id.
    Raises KeyError with a clear message if the ID does not exist.
    """
    fleet = load_fleet()
    for system in fleet:
        if system["system_id"] == system_id:
            return system
    raise KeyError(
        f"System '{system_id}' not found in fleet. "
        f"Valid IDs are SYS_001 – SYS_{len(fleet):03d}."
    )


def update_system(system_id: str, fields: dict[str, Any]) -> dict:
    """
    Merge `fields` into the system identified by system_id, persist to disk,
    and return the updated system dict.

    Raises KeyError if system_id does not exist.
    Raises ValueError if `fields` contains keys not in the system schema.

    Example:
        update_system("SYS_042", {"status": "healthy", "anomaly_type": None})
    """
    fleet  = load_fleet()
    target = None

    for system in fleet:
        if system["system_id"] == system_id:
            target = system
            break

    if target is None:
        raise KeyError(
            f"System '{system_id}' not found in fleet. "
            f"Valid IDs are SYS_001 – SYS_{len(fleet):03d}."
        )

    # Guard against typos introducing unknown fields
    unknown = set(fields) - set(target)
    if unknown:
        raise ValueError(f"Unknown fields for system update: {unknown}")

    target.update(fields)
    target["last_updated"] = datetime.now(timezone.utc).isoformat()

    save_fleet(fleet)
    return target


# ── Escalations ───────────────────────────────────────────────────────────────

def load_escalations() -> list[dict]:
    """
    Load and return all escalation tickets.
    Returns an empty list if escalations.json does not exist yet.
    """
    if not ESCALATIONS_PATH.exists():
        return []

    with open(ESCALATIONS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_escalation(ticket: dict) -> None:
    """
    Append a single escalation ticket to escalations.json.
    Creates the file if it does not exist.

    Expected ticket fields:
        ticket_id, system_id, reason, severity, created_at
    """
    escalations = load_escalations()
    escalations.append(ticket)

    tmp_path = ESCALATIONS_PATH.with_suffix(".tmp.json")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(escalations, f, indent=2, ensure_ascii=False)

    os.replace(tmp_path, ESCALATIONS_PATH)