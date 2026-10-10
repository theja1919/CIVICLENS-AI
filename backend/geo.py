"""
geo.py — Geographic utilities for CivicLens AI.

Haversine distance calculation for duplicate detection.
No external APIs — pure Python math only.
"""

from __future__ import annotations

import math
from typing import Optional

_EARTH_RADIUS_M = 6_371_000  # metres


def haversine_metres(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> float:
    """
    Return the great-circle distance between two WGS-84 points in metres.

    Uses the Haversine formula — accurate to within ~0.5% for distances
    relevant to civic issue reporting (< 10 km).
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return _EARTH_RADIUS_M * c


def find_nearby_reports(
    target_lat: float,
    target_lon: float,
    candidates: list,          # list of Report ORM objects
    radius_m: float = 100.0,
    exclude_id: Optional[int] = None,
) -> list[dict]:
    """
    Return reports within `radius_m` metres of (target_lat, target_lon).

    Only considers reports that have both latitude and longitude set.
    Reports with missing coordinates are silently skipped.

    Args:
        target_lat:  Reference latitude.
        target_lon:  Reference longitude.
        candidates:  SQLAlchemy Report objects to compare against.
        radius_m:    Search radius in metres (default 100 m).
        exclude_id:  ID to exclude (the report being queried).

    Returns:
        List of dicts: {id, category, status, distance_m, priority_score}
        sorted by distance ascending.
    """
    results = []
    for r in candidates:
        if r.latitude is None or r.longitude is None:
            continue
        if exclude_id is not None and r.id == exclude_id:
            continue
        dist = haversine_metres(target_lat, target_lon, r.latitude, r.longitude)
        if dist <= radius_m:
            results.append({
                "id": r.id,
                "category": r.category,
                "status": r.status,
                "distance_m": round(dist, 1),
                "priority_score": r.priority_score,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            })
    results.sort(key=lambda x: x["distance_m"])
    return results
