"""Geo utilities — haversine fallback + OSRM distance matrix client."""

import logging
import math
from typing import Optional

import httpx

from krankenfahrt.config import config

logger = logging.getLogger(__name__)


# ── Haversine (air-line distance) ────────────────────────────────────────


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
    """Estimate travel time in minutes from air-line distance."""
    return max(1, int((distance_km / avg_speed_kmh) * 60))


# ── OSRM client (road-distance routing) ──────────────────────────────────


async def _osrm_request(
    service: str,
    coordinates: str,
    timeout: float = 10.0,
) -> dict:
    """Low-level OSRM HTTP request.

    Args:
        service: OSRM service name (route, table, nearest)
        coordinates: OSRM coordinate string (lon,lat;lon,lat;...)
        timeout: Request timeout in seconds
    """
    url = f"{config.OSRM_BASE_URL}/{service}/v1/driving/{coordinates}"
    params = {"overview": "false", "annotations": "duration,distance"}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error: {data.get('code')} - {data.get('message', '')}")

    return data


async def get_route(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> tuple[float, float]:
    """Get road distance (km) and duration (minutes) between two points via OSRM.

    Returns:
        (distance_km, duration_minutes)
    """
    coords = f"{lon1},{lat1};{lon2},{lat2}"
    data = await _osrm_request("route", coords)

    route = data["routes"][0]
    distance_m = route["distance"]  # meters
    duration_s = route["duration"]  # seconds

    distance_km = distance_m / 1000.0
    duration_min = duration_s / 60.0
    return round(distance_km, 2), round(duration_min, 1)


async def get_distance_matrix(
    origins: list[tuple[float, float]],
    destinations: list[tuple[float, float]],
) -> list[list[float]]:
    """Query OSRM for a distance/duration matrix.

    Args:
        origins: List of (lat, lon) origin coordinates
        destinations: List of (lat, lon) destination coordinates

    Returns:
        2D list of distances in km: result[origin_idx][dest_idx]
    """
    all_coords = origins + destinations
    coord_str = ";".join(f"{lon},{lat}" for lat, lon in all_coords)

    # Build sources/destinations indices for OSRM table
    n_origins = len(origins)
    sources = ";".join(str(i) for i in range(n_origins))
    destinations_indices = ";".join(
        str(i) for i in range(n_origins, n_origins + len(destinations))
    )

    url = f"{config.OSRM_BASE_URL}/table/v1/driving/{coord_str}"
    params = {
        "sources": sources,
        "destinations": destinations_indices,
        "annotations": "distance",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != "Ok":
        raise RuntimeError(
            f"OSRM table error: {data.get('code')} - {data.get('message', '')}"
        )

    # Convert meters to km
    distances_m = data["distances"]  # 2D list in meters
    return [
        [round(d / 1000.0, 2) if d is not None else float("inf") for d in row]
        for row in distances_m
    ]


async def get_distance_matrix_duration(
    origins: list[tuple[float, float]],
    destinations: list[tuple[float, float]],
) -> list[list[float]]:
    """Like get_distance_matrix but returns duration in minutes."""
    all_coords = origins + destinations
    coord_str = ";".join(f"{lon},{lat}" for lat, lon in all_coords)

    n_origins = len(origins)
    sources = ";".join(str(i) for i in range(n_origins))
    destinations_indices = ";".join(
        str(i) for i in range(n_origins, n_origins + len(destinations))
    )

    url = f"{config.OSRM_BASE_URL}/table/v1/driving/{coord_str}"
    params = {
        "sources": sources,
        "destinations": destinations_indices,
        "annotations": "duration",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("code") != "Ok":
        raise RuntimeError(
            f"OSRM table error: {data.get('code')} - {data.get('message', '')}"
        )

    durations_s = data["durations"]  # 2D list in seconds
    return [
        [round(d / 60.0, 1) if d is not None else float("inf") for d in row]
        for row in durations_s
    ]


# ── Smart distance (OSRM with haversine fallback) ────────────────────────


async def get_distance_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Road distance if OSRM is available, otherwise air-line distance."""
    if config.USE_OSRM:
        try:
            dist, _ = await get_route(lat1, lon1, lat2, lon2)
            return dist
        except Exception:
            logger.warning("OSRM route failed, falling back to haversine", exc_info=True)
    return round(haversine_km(lat1, lon1, lat2, lon2), 2)


async def get_eta_minutes(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Road ETA if OSRM is available, otherwise estimate from air-line."""
    if config.USE_OSRM:
        try:
            _, duration = await get_route(lat1, lon1, lat2, lon2)
            return duration
        except Exception:
            logger.warning("OSRM route failed, falling back to estimate", exc_info=True)
    dist = haversine_km(lat1, lon1, lat2, lon2)
    return float(format_eta_minutes(dist))


# ── Health check ─────────────────────────────────────────────────────────


async def check_osrm_health() -> bool:
    """Check if the OSRM server is reachable."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{config.OSRM_BASE_URL}/route/v1/driving/0,0;1,1")
            return resp.status_code == 200
    except Exception:
        return False
