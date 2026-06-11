"""
fleet_store.py

Single point of contact between the application and the database (or JSON fallback).
Every tool, agent node, and API endpoint reads/writes fleet data through here.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db.session import is_db_available, init_db, db_session
from db.models import System as DBSystem, Escalation as DBEscalation

# ── Paths ─────────────────────────────────────────────────────────────────────

_DATA_DIR        = Path(__file__).parent
FLEET_PATH       = _DATA_DIR / "fleet.json"
ESCALATIONS_PATH = _DATA_DIR / "escalations.json"

# ── In-memory cache ───────────────────────────────────────────────────────────
_fleet_cache: list[dict] | None = None


# ── Translation Helpers ───────────────────────────────────────────────────────

def _system_to_dict(sys_obj: DBSystem) -> dict:
    return {
        "system_id":           sys_obj.system_id,
        "location":            sys_obj.location,
        "latitude":            sys_obj.latitude,
        "longitude":           sys_obj.longitude,
        "system_type":         sys_obj.system_type,
        "solar_capacity_kw":   sys_obj.solar_capacity_kw,
        "solar_output_kw":     sys_obj.solar_output_kw,
        "expected_output_kw":  sys_obj.expected_output_kw,
        "battery_soc_pct":     sys_obj.battery_soc_pct,
        "grid_feed_in_kw":     sys_obj.grid_feed_in_kw,
        "status":              sys_obj.status,
        "anomaly_type":        sys_obj.anomaly_type,
        "last_updated":        sys_obj.last_updated,
        "alerts":              sys_obj.alerts or [],
        "history":             sys_obj.history or [],
    }


def _escalation_to_dict(esc_obj: DBEscalation) -> dict:
    return {
        "ticket_id":  esc_obj.ticket_id,
        "system_id":  esc_obj.system_id,
        "reason":     esc_obj.reason,
        "severity":   esc_obj.severity,
        "created_at": esc_obj.created_at,
        "status":     esc_obj.status,
    }


# ── Fleet ─────────────────────────────────────────────────────────────────────

def load_fleet(force: bool = False) -> list[dict]:
    """
    Load and return the full fleet.
    Tries PostgreSQL first, falling back to JSON.
    """
    global _fleet_cache
    if _fleet_cache is not None and not force:
        return _fleet_cache

    init_db()
    if is_db_available():
        try:
            session = db_session()
            systems = session.query(DBSystem).order_by(DBSystem.system_id).all()
            if systems:
                _fleet_cache = [_system_to_dict(s) for s in systems]
                return _fleet_cache
        except Exception:
            pass

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
    Save fleet to PostgreSQL and JSON fallback.
    """
    global _fleet_cache

    init_db()
    if is_db_available():
        try:
            session = db_session()
            for system_data in fleet:
                sys_obj = session.query(DBSystem).filter_by(system_id=system_data["system_id"]).first()
                if not sys_obj:
                    sys_obj = DBSystem(system_id=system_data["system_id"])
                    session.add(sys_obj)

                sys_obj.location = system_data["location"]
                sys_obj.latitude = system_data.get("latitude", 0.0)
                sys_obj.longitude = system_data.get("longitude", 0.0)
                sys_obj.system_type = system_data["system_type"]
                sys_obj.solar_capacity_kw = system_data["solar_capacity_kw"]
                sys_obj.solar_output_kw = system_data["solar_output_kw"]
                sys_obj.expected_output_kw = system_data["expected_output_kw"]
                sys_obj.battery_soc_pct = system_data["battery_soc_pct"]
                sys_obj.grid_feed_in_kw = system_data["grid_feed_in_kw"]
                sys_obj.status = system_data["status"]
                sys_obj.anomaly_type = system_data["anomaly_type"]
                sys_obj.last_updated = system_data["last_updated"]
                sys_obj.alerts = system_data["alerts"]
                sys_obj.history = system_data.get("history", [])

            session.commit()
        except Exception:
            session.rollback()

    # JSON fallback
    tmp_path = FLEET_PATH.with_suffix(".tmp.json")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(fleet, f, indent=2, ensure_ascii=False)

    os.replace(tmp_path, FLEET_PATH)
    _fleet_cache = fleet


def get_system(system_id: str) -> dict:
    """
    Return the system dict for system_id.
    """
    init_db()
    if is_db_available():
        try:
            session = db_session()
            sys_obj = session.query(DBSystem).filter_by(system_id=system_id).first()
            if sys_obj:
                return _system_to_dict(sys_obj)
        except Exception:
            pass

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
    Merge `fields` into system, persist, and return updated system.
    """
    init_db()
    if is_db_available():
        try:
            session = db_session()
            sys_obj = session.query(DBSystem).filter_by(system_id=system_id).first()
            if sys_obj:
                # Schema safety check
                allowed_cols = {c.name for c in DBSystem.__table__.columns}
                unknown = set(fields) - allowed_cols
                if unknown:
                    raise ValueError(f"Unknown fields for system update: {unknown}")

                for k, v in fields.items():
                    setattr(sys_obj, k, v)
                sys_obj.last_updated = datetime.now(timezone.utc).isoformat()
                session.commit()

                # Sync JSON file fallback
                updated_dict = _system_to_dict(sys_obj)
                global _fleet_cache
                if _fleet_cache is not None:
                    for i, s in enumerate(_fleet_cache):
                        if s["system_id"] == system_id:
                            _fleet_cache[i].update(fields)
                            _fleet_cache[i]["last_updated"] = sys_obj.last_updated
                            break
                    save_fleet(_fleet_cache)
                else:
                    systems = session.query(DBSystem).order_by(DBSystem.system_id).all()
                    _fleet_cache = [_system_to_dict(s) for s in systems]
                    save_fleet(_fleet_cache)

                return updated_dict
        except ValueError as ve:
            raise ve
        except Exception:
            session.rollback()

    # JSON fallback
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
    Load all escalations.
    """
    init_db()
    if is_db_available():
        try:
            session = db_session()
            escalations = session.query(DBEscalation).all()
            if escalations:
                return [_escalation_to_dict(e) for e in escalations]
        except Exception:
            pass

    if not ESCALATIONS_PATH.exists():
        return []

    with open(ESCALATIONS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_escalation(ticket: dict) -> None:
    """
    Save single escalation ticket.
    """
    init_db()
    if is_db_available():
        try:
            session = db_session()
            esc_obj = session.query(DBEscalation).filter_by(ticket_id=ticket["ticket_id"]).first()
            if not esc_obj:
                esc_obj = DBEscalation(
                    ticket_id=ticket["ticket_id"],
                    system_id=ticket["system_id"],
                    reason=ticket["reason"],
                    severity=ticket["severity"],
                    created_at=ticket["created_at"],
                    status=ticket["status"],
                )
                session.add(esc_obj)
            else:
                esc_obj.status = ticket["status"]
            session.commit()
        except Exception:
            session.rollback()

    # JSON fallback sync
    escalations = load_escalations()
    exists = False
    for i, esc in enumerate(escalations):
        if esc["ticket_id"] == ticket["ticket_id"]:
            escalations[i] = ticket
            exists = True
            break
    if not exists:
        escalations.append(ticket)

    tmp_path = ESCALATIONS_PATH.with_suffix(".tmp.json")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(escalations, f, indent=2, ensure_ascii=False)

    os.replace(tmp_path, ESCALATIONS_PATH)