"""
generate_fleet.py

Generates the GridMind mock fleet (fleet.json).
Run once to seed the data layer. Everything else reads from fleet.json via fleet_store.py.

Usage:
    python -m data.generate_fleet
    python -m data.generate_fleet --seed 99     # reproducible output
    python -m data.generate_fleet --out path/to/fleet.json
"""

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from faker import Faker

# ── Constants ────────────────────────────────────────────────────────────────

FLEET_SIZE = 50
OUTPUT_PATH = Path(__file__).parent / "fleet.json"

BERLIN_DISTRICTS = [
    "Mitte", "Prenzlauer Berg", "Friedrichshain", "Kreuzberg", "Neukölln",
    "Tempelhof", "Schöneberg", "Charlottenburg", "Spandau", "Steglitz",
    "Zehlendorf", "Lichtenberg", "Marzahn", "Pankow", "Reinickendorf",
    "Treptow", "Köpenick", "Weißensee", "Hohenschönhausen", "Hellersdorf",
]

SYSTEM_TYPES = ["solar_only", "solar+battery", "solar+battery+ev"]

# Anomaly distribution from PRD §11.1
ANOMALY_DISTRIBUTION = [
    ("healthy",       35),
    ("low_output",     8),
    ("offline",        4),
    ("battery_drain",  2),
    ("inverter_fault", 1),
]

# Status mapping — anomaly_type → status
ANOMALY_TO_STATUS = {
    "healthy":       "healthy",
    "low_output":    "degraded",
    "offline":       "offline",
    "battery_drain": "warning",
    "inverter_fault":"degraded",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_anomaly_list() -> list[str]:
    """Return a shuffled list of 50 anomaly labels matching the PRD distribution."""
    labels = [anomaly for anomaly, count in ANOMALY_DISTRIBUTION for _ in range(count)]
    random.shuffle(labels)
    return labels


def _solar_capacity(system_type: str, rng: random.Random) -> float:
    """Installed capacity in kW — larger systems for more complex types."""
    ranges = {
        "solar_only":          (5.0,  15.0),
        "solar+battery":       (8.0,  25.0),
        "solar+battery+ev":    (12.0, 40.0),
    }
    lo, hi = ranges[system_type]
    return round(rng.uniform(lo, hi), 2)


def _outputs(anomaly: str, capacity: float, rng: random.Random) -> tuple[float, float]:
    """Return (solar_output_kw, expected_output_kw) based on anomaly type."""
    # Expected is 70–95% of capacity (time-of-day proxy)
    expected = round(capacity * rng.uniform(0.70, 0.95), 2)

    match anomaly:
        case "healthy":
            output = round(expected * rng.uniform(0.90, 1.05), 2)   # within ±10%
        case "low_output":
            output = round(expected * rng.uniform(0.15, 0.49), 2)   # below 50%
        case "offline":
            output = 0.0
        case "battery_drain":
            output = round(expected * rng.uniform(0.60, 0.85), 2)   # somewhat reduced
        case "inverter_fault":
            output = 0.0                                              # zero despite irradiance
        case _:
            output = expected

    return output, expected


def _battery_soc(anomaly: str, system_type: str, rng: random.Random) -> float | None:
    """State of charge — None for solar_only (no battery)."""
    if system_type == "solar_only":
        return None

    match anomaly:
        case "battery_drain":
            return round(rng.uniform(5.0, 25.0), 1)    # critically low
        case "offline":
            return None                                  # no telemetry
        case _:
            return round(rng.uniform(40.0, 95.0), 1)


def _grid_feed_in(output: float, anomaly: str, rng: random.Random) -> float:
    """Energy exported to grid — zero when offline or faulted."""
    if anomaly in ("offline", "inverter_fault"):
        return 0.0
    return round(output * rng.uniform(0.3, 0.7), 2)


def _alerts(anomaly: str, system_id: str) -> list[str]:
    """Human-readable alert messages surfaced in the dashboard."""
    match anomaly:
        case "healthy":
            return []
        case "low_output":
            return [f"[{system_id}] Solar output below 50% of expected for current irradiance."]
        case "offline":
            return [
                f"[{system_id}] No telemetry received in last 30 minutes.",
                f"[{system_id}] System unreachable — field inspection may be required.",
            ]
        case "battery_drain":
            return [f"[{system_id}] Battery SOC dropping faster than expected discharge rate."]
        case "inverter_fault":
            return [
                f"[{system_id}] Inverter output zero despite solar irradiance detected.",
                f"[{system_id}] Possible inverter fault — consider restart_inverter action.",
            ]
        case _:
            return []


# ── Core builder ─────────────────────────────────────────────────────────────

def build_fleet(seed: int | None = None) -> list[dict]:
    """
    Build and return the full 50-system fleet as a list of dicts.
    Pass a seed for reproducible output (useful in tests and evals).
    """
    fake = Faker("de_DE")
    rng  = random.Random(seed)
    if seed is not None:
        Faker.seed(seed)

    anomaly_labels = _build_anomaly_list()
    now = datetime.now(timezone.utc)

    systems = []
    for i, anomaly in enumerate(anomaly_labels, start=1):
        system_id   = f"SYS_{i:03d}"
        system_type = rng.choice(SYSTEM_TYPES)
        capacity    = _solar_capacity(system_type, rng)
        output, expected = _outputs(anomaly, capacity, rng)
        soc         = _battery_soc(anomaly, system_type, rng)
        feed_in     = _grid_feed_in(output, anomaly, rng)

        # Offline systems: stale timestamp (30–90 min ago)
        if anomaly == "offline":
            stale_delta = rng.randint(30, 90) * 60
            last_updated = datetime.fromtimestamp(
                now.timestamp() - stale_delta, tz=timezone.utc
            ).isoformat()
        else:
            last_updated = now.isoformat()

        system: dict = {
            "system_id":           system_id,
            "location":            rng.choice(BERLIN_DISTRICTS),
            "system_type":         system_type,
            "solar_capacity_kw":   capacity,
            "solar_output_kw":     output,
            "expected_output_kw":  expected,
            "battery_soc_pct":     soc,
            "grid_feed_in_kw":     feed_in,
            "status":              ANOMALY_TO_STATUS[anomaly],
            "anomaly_type":        None if anomaly == "healthy" else anomaly,
            "last_updated":        last_updated,
            "history":             [],          # populated in Task 2
            "alerts":              _alerts(anomaly, system_id),
        }
        systems.append(system)

    return systems


# ── Validation ────────────────────────────────────────────────────────────────

def validate(fleet: list[dict]) -> None:
    """
    Lightweight sanity checks — catches distribution drift or schema gaps
    before the file is written. Raises ValueError on failure.
    """
    df = pd.DataFrame(fleet)

    # Schema completeness
    required = {
        "system_id", "location", "system_type", "solar_capacity_kw",
        "solar_output_kw", "expected_output_kw", "battery_soc_pct",
        "grid_feed_in_kw", "status", "anomaly_type", "last_updated",
        "history", "alerts",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Schema missing fields: {missing}")

    # Anomaly distribution
    actual = (
        df["anomaly_type"]
        .fillna("healthy")
        .value_counts()
        .to_dict()
    )
    expected_dist = dict(ANOMALY_DISTRIBUTION)
    for anomaly, count in expected_dist.items():
        if actual.get(anomaly, 0) != count:
            raise ValueError(
                f"Distribution mismatch for '{anomaly}': "
                f"expected {count}, got {actual.get(anomaly, 0)}"
            )

    # No negative outputs
    if (df["solar_output_kw"] < 0).any():
        raise ValueError("Negative solar output detected.")

    # Offline systems should have zero output
    offline_mask = df["anomaly_type"] == "offline"
    if (df.loc[offline_mask, "solar_output_kw"] != 0).any():
        raise ValueError("Offline systems must have solar_output_kw == 0.")

    # Inverter fault systems should have zero output
    inv_mask = df["anomaly_type"] == "inverter_fault"
    if (df.loc[inv_mask, "solar_output_kw"] != 0).any():
        raise ValueError("Inverter fault systems must have solar_output_kw == 0.")

    print(f"✓ Validation passed — {len(fleet)} systems, distribution correct.")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate GridMind mock fleet data.")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")
    parser.add_argument("--out",  type=str, default=str(OUTPUT_PATH), help="Output path for fleet.json.")
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fleet = build_fleet(seed=args.seed)
    validate(fleet)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fleet, f, indent=2, ensure_ascii=False)

    # Summary printed to stdout — useful in CI and during dev
    df = pd.DataFrame(fleet)
    print(f"✓ Written → {out_path}")
    print(f"\nFleet summary:")
    print(df["status"].value_counts().to_string())
    print(f"\nAnomaly breakdown:")
    print(df["anomaly_type"].fillna("healthy").value_counts().to_string())


if __name__ == "__main__":
    main()