"""
generate_history.py

Populates the `history` field for every system in fleet.json with 24 hourly
readings. Reads fleet.json, enriches in-memory, writes back in place.

Realism guarantees:
  - Solar irradiance curve: zero at night, sine-peaked at solar noon (~13:00 UTC)
  - Anomaly progression: systems degrade over time, not instantly at t=0
  - Offline systems: history entries are None after the last known reading
  - Battery SOC: tracks charge/discharge realistically across the day

Usage:
    python -m data.generate_history
    python -m data.generate_history --seed 42
    python -m data.generate_history --fleet path/to/fleet.json
"""

import argparse
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

FLEET_PATH = Path(__file__).parent / "fleet.json"

# Hours (0–23 UTC) where solar production is possible
SUNRISE_HOUR = 5
SUNSET_HOUR  = 20
SOLAR_PEAK_HOUR = 13   # ~1pm UTC — solar noon for Berlin


# ── Irradiance model ─────────────────────────────────────────────────────────

def _irradiance_factor(hour_utc: int) -> float:
    """
    Returns 0.0–1.0 representing available solar irradiance at a given UTC hour.
    Uses a half-sine curve between sunrise and sunset, zero outside that window.
    """
    if hour_utc <= SUNRISE_HOUR or hour_utc >= SUNSET_HOUR:
        return 0.0
    window = SUNSET_HOUR - SUNRISE_HOUR
    position = hour_utc - SUNRISE_HOUR
    return math.sin(math.pi * position / window)


# ── Per-anomaly history generators ───────────────────────────────────────────

def _healthy_reading(
    hour: int,
    capacity: float,
    has_battery: bool,
    prev_soc: float | None,
    rng: random.Random,
) -> dict:
    irr   = _irradiance_factor(hour)
    exp   = round(capacity * irr * rng.uniform(0.70, 0.90), 2)
    out   = round(exp * rng.uniform(0.92, 1.05), 2)
    feed  = round(out * rng.uniform(0.30, 0.65), 2)
    soc   = _next_soc(prev_soc, out, capacity, irr, rng) if has_battery else None
    return {"solar_output_kw": out, "expected_output_kw": exp,
            "battery_soc_pct": soc, "grid_feed_in_kw": feed, "status": "healthy"}


def _low_output_reading(
    hour: int,
    capacity: float,
    has_battery: bool,
    prev_soc: float | None,
    rng: random.Random,
    degradation_start: int,
) -> dict:
    irr = _irradiance_factor(hour)
    exp = round(capacity * irr * rng.uniform(0.70, 0.90), 2)

    if hour < degradation_start:
        # Still healthy
        out    = round(exp * rng.uniform(0.92, 1.05), 2)
        status = "healthy"
    else:
        # Progressive degradation: output factor drops from ~0.8 → 0.2
        progress = min((hour - degradation_start) / 4, 1.0)
        factor   = 0.80 - progress * 0.65
        out      = round(exp * max(factor, 0.10), 2)
        status   = "degraded"

    feed = round(out * rng.uniform(0.30, 0.65), 2)
    soc  = _next_soc(prev_soc, out, capacity, irr, rng) if has_battery else None
    return {"solar_output_kw": out, "expected_output_kw": exp,
            "battery_soc_pct": soc, "grid_feed_in_kw": feed, "status": status}


def _offline_reading(is_null: bool) -> dict:
    """After the last telemetry window, all fields are None."""
    if is_null:
        return {"solar_output_kw": None, "expected_output_kw": None,
                "battery_soc_pct": None, "grid_feed_in_kw": None, "status": None}
    # Readings before going offline look healthy
    return None   # caller will use healthy generator for pre-offline hours


def _battery_drain_reading(
    hour: int,
    capacity: float,
    prev_soc: float | None,
    rng: random.Random,
    drain_start: int,
) -> dict:
    irr = _irradiance_factor(hour)
    exp = round(capacity * irr * rng.uniform(0.70, 0.90), 2)
    out = round(exp * rng.uniform(0.60, 0.85), 2)
    feed = round(out * rng.uniform(0.20, 0.50), 2)

    if prev_soc is None:
        soc = round(rng.uniform(70.0, 90.0), 1)
    elif hour < drain_start:
        soc = _next_soc(prev_soc, out, capacity, irr, rng)
    else:
        # Drain faster than expected: extra -2 to -4% per hour
        excess_drain = rng.uniform(2.0, 4.0)
        soc = round(max(prev_soc - excess_drain, 2.0), 1)

    status = "warning" if hour >= drain_start else "healthy"
    return {"solar_output_kw": out, "expected_output_kw": exp,
            "battery_soc_pct": soc, "grid_feed_in_kw": feed, "status": status}


def _inverter_fault_reading(
    hour: int,
    capacity: float,
    has_battery: bool,
    prev_soc: float | None,
    rng: random.Random,
    fault_hour: int,
) -> dict:
    irr = _irradiance_factor(hour)
    exp = round(capacity * irr * rng.uniform(0.70, 0.90), 2)

    if hour < fault_hour:
        out    = round(exp * rng.uniform(0.92, 1.05), 2)
        feed   = round(out * rng.uniform(0.30, 0.65), 2)
        status = "healthy"
    else:
        out    = 0.0
        feed   = 0.0
        status = "degraded"

    soc = _next_soc(prev_soc, out, capacity, irr, rng) if has_battery else None
    return {"solar_output_kw": out, "expected_output_kw": exp,
            "battery_soc_pct": soc, "grid_feed_in_kw": feed, "status": status}


# ── SOC model ────────────────────────────────────────────────────────────────

def _next_soc(
    prev: float | None,
    output: float,
    capacity: float,
    irr: float,
    rng: random.Random,
) -> float:
    """
    Simple SOC model:
    - Daytime with output → charges slightly
    - Night or low output → discharges slightly
    - Random noise ±0.5%
    """
    if prev is None:
        return round(rng.uniform(50.0, 85.0), 1)

    if irr > 0.3 and output > capacity * 0.3:
        delta = rng.uniform(0.5, 2.0)    # charging
    else:
        delta = -rng.uniform(0.5, 2.5)   # discharging

    return round(min(max(prev + delta + rng.uniform(-0.5, 0.5), 0.0), 100.0), 1)


# ── Core builder ─────────────────────────────────────────────────────────────

def build_history(system: dict, now: datetime, rng: random.Random) -> list[dict]:
    """
    Build 24 hourly readings for a single system.
    Returns a list of 24 dicts, oldest first (index 0 = 23h ago).
    """
    anomaly     = system["anomaly_type"]
    capacity    = system["solar_capacity_kw"]
    has_battery = system["system_type"] != "solar_only"

    # Anomaly onset hours — injected late in the 24h window for realism
    degradation_start = rng.randint(18, 21)   # low_output
    drain_start       = rng.randint(16, 19)   # battery_drain
    fault_hour        = rng.randint(20, 22)   # inverter_fault

    # Offline: last N readings are None (30–90 min → 1–2 hours)
    offline_gap_hours = rng.randint(1, 2) if anomaly == "offline" else 0

    readings  = []
    prev_soc  = None

    for i in range(24):
        # i=0 is 23 hours ago, i=23 is the most recent hour
        ts    = now - timedelta(hours=(23 - i))
        hour  = ts.hour

        if anomaly == "offline" and i >= (24 - offline_gap_hours):
            entry = {"solar_output_kw": None, "expected_output_kw": None,
                     "battery_soc_pct": None, "grid_feed_in_kw": None,
                     "status": None}
        elif anomaly == "low_output":
            entry = _low_output_reading(i, capacity, has_battery, prev_soc, rng, degradation_start)
        elif anomaly == "battery_drain":
            entry = _battery_drain_reading(i, capacity, prev_soc, rng, drain_start)
        elif anomaly == "inverter_fault":
            entry = _inverter_fault_reading(i, capacity, has_battery, prev_soc, rng, fault_hour)
        else:
            entry = _healthy_reading(i, capacity, has_battery, prev_soc, rng)

        prev_soc = entry.get("battery_soc_pct")
        entry["timestamp"] = ts.isoformat()
        readings.append(entry)

    return readings


# ── Validation ────────────────────────────────────────────────────────────────

def validate(fleet: list[dict]) -> None:
    for system in fleet:
        sid     = system["system_id"]
        history = system["history"]

        if len(history) != 24:
            raise ValueError(f"{sid}: expected 24 history entries, got {len(history)}")

        anomaly = system["anomaly_type"]

        if anomaly == "offline":
            # Last 1–2 entries must be None
            last = history[-1]
            if last["solar_output_kw"] is not None:
                raise ValueError(f"{sid}: offline system must have null final reading")

        if anomaly == "inverter_fault":
            # At least the last entry must have zero output
            if history[-1]["solar_output_kw"] != 0.0:
                raise ValueError(f"{sid}: inverter_fault system must end with zero output")

        if anomaly == "battery_drain":
            # SOC at end must be lower than SOC at start (overall drain)
            socs = [r["battery_soc_pct"] for r in history if r["battery_soc_pct"] is not None]
            if socs and socs[-1] >= socs[0]:
                raise ValueError(f"{sid}: battery_drain SOC should trend downward")

    print(f"Success - History validation passed — {len(fleet)} systems, 24 readings each.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Populate 24h history into fleet.json.")
    parser.add_argument("--seed",  type=int, default=None)
    parser.add_argument("--fleet", type=str, default=str(FLEET_PATH))
    args = parser.parse_args()

    fleet_path = Path(args.fleet)
    if not fleet_path.exists():
        raise FileNotFoundError(f"fleet.json not found at {fleet_path}. Run generate_fleet.py first.")

    with open(fleet_path, encoding="utf-8") as f:
        fleet = json.load(f)

    rng = random.Random(args.seed)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    for system in fleet:
        system["history"] = build_history(system, now, rng)

    validate(fleet)

    with open(fleet_path, "w", encoding="utf-8") as f:
        json.dump(fleet, f, indent=2, ensure_ascii=False)

    print(f"Written to {fleet_path}")

    # Synchronize to BigQuery/DuckDB mock layer
    try:
        from db.bigquery_client import sync_json_to_duckdb
        sync_json_to_duckdb()
        print("Synced history to BigQuery/DuckDB time-series database.")
    except Exception as e:
        print(f"Warning: DuckDB sync failed: {e}")

    # Spot-check: print last 3 history entries for one anomalous system
    sample = next((s for s in fleet if s["anomaly_type"] == "inverter_fault"), fleet[0])
    print(f"\nSample — {sample['system_id']} ({sample['anomaly_type']}) last 3 readings:")
    for r in sample["history"][-3:]:
        print(f"  {r['timestamp']}  output={r['solar_output_kw']}  status={r['status']}")


if __name__ == "__main__":
    main()