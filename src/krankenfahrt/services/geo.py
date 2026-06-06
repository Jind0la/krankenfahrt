"""Geo utilities — distance calculation and (future) OSRM integration."""

import math
from typing import Optional


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometers."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def format_eta_minutes(distance_km: float, avg_speed_kmh: float = 30.0) -> int:
    """Estimate travel time in minutes."""
    return max(1, int((distance_km / avg_speed_kmh) * 60))


# FUTURE: OSRM distance matrix client
# async def get_distance_matrix(
#     origins: list[tuple[float, float]],
#     destinations: list[tuple[float, float]],
# ) -> list[list[float]]:
#     """Query OSRM for distance matrix."""
#     ...
