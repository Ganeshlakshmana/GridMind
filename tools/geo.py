"""
tools/geo.py

Geospatial utility functions for coordinate transformations and spatial analysis.
"""

import math
from typing import Any

# ── Centroids for Berlin Zones ───────────────────────────────────────────────
ZONE_CENTROIDS = {
    "ZONE_NORTH": (52.57, 13.40),
    "ZONE_SOUTH": (52.46, 13.40),
    "ZONE_EAST":  (52.51, 13.52),
    "ZONE_WEST":  (52.51, 13.25),
    "ZONE_CENTER": (52.51, 13.40),
}


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points on the Earth's surface
    using the Haversine formula. Returns distance in kilometers.
    """
    R = 6371.0  # Earth's radius in km

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return round(R * c, 3)


def get_grid_zone(lat: float, lon: float) -> str:
    """
    Assign a system to one of the 5 Berlin zones based on closest distance to centroids.
    """
    min_dist = float("inf")
    closest_zone = "ZONE_CENTER"

    for zone, (z_lat, z_lon) in ZONE_CENTROIDS.items():
        dist = haversine_distance(lat, lon, z_lat, z_lon)
        if dist < min_dist:
            min_dist = dist
            closest_zone = zone

    return closest_zone


def grid_zone_clustering(systems: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Group a list of systems into grid zones.
    """
    zones: dict[str, list[dict[str, Any]]] = {z: [] for z in ZONE_CENTROIDS}
    for system in systems:
        lat = system.get("latitude")
        lon = system.get("longitude")
        if lat is not None and lon is not None:
            zone = get_grid_zone(lat, lon)
            zones[zone].append(system)
    return zones


def nearest_neighbor_lookup(
    target_lat: float,
    target_lon: float,
    systems: list[dict[str, Any]],
    k: int = 5,
) -> list[dict[str, Any]]:
    """
    Find the K nearest systems to a target coordinate location.
    """
    scored_systems = []
    for s in systems:
        lat = s.get("latitude")
        lon = s.get("longitude")
        if lat is not None and lon is not None:
            dist = haversine_distance(target_lat, target_lon, lat, lon)
            scored = dict(s)
            scored["distance_km"] = dist
            scored_systems.append(scored)

    # Sort by distance
    scored_systems.sort(key=lambda x: x["distance_km"])
    return scored_systems[:k]
