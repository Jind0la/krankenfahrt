"""OSRM distance matrix client with Haversine fallback.

Calls OSRM's /table endpoint for road-distance matrices. Falls back to
Haversine great-circle distances when OSRM is unreachable or returns errors.

Configuration (from environment):
    USE_OSRM=1          — enable OSRM (default: 0, Haversine only)
    OSRM_BASE_URL       — OSRM server URL (default: http://localhost:5000)
    OSRM_TIMEOUT        — HTTP timeout per request in seconds (default: 2.0)
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# WGS-84 Earth radius in km
EARTH_RADIUS_KM: float = 6371.0

# Default OSRM connection settings
DEFAULT_OSRM_BASE_URL = "http://localhost:5000"
DEFAULT_OSRM_TIMEOUT = 2.0


class OSRMError(Exception):
    """Raised when OSRM returns a non-Ok response or is unreachable."""


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometers.

    Uses the Haversine formula with WGS-84 Earth radius.
    """
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(a))


def haversine_matrix(
    coordinates: list[tuple[float, float]],
) -> list[list[float]]:
    """Build a full pairwise distance matrix using Haversine formula.

    Args:
        coordinates: List of (lat, lon) pairs.

    Returns:
        Square matrix: matrix[i][j] = distance from i to j in km.
    """
    n = len(coordinates)
    matrix: list[list[float]] = []
    for i in range(n):
        row: list[float] = []
        for j in range(n):
            if i == j:
                row.append(0.0)
            else:
                lat1, lon1 = coordinates[i]
                lat2, lon2 = coordinates[j]
                row.append(haversine_km(lat1, lon1, lat2, lon2))
        matrix.append(row)
    return matrix


class OSRMClient:
    """Async client for OSRM distance matrix (/table endpoint).

    Usage:
        client = OSRMClient(base_url="http://localhost:5000")
        matrix = await client.distance_matrix(coordinates)
        # Falls back to Haversine if OSRM is unreachable.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_OSRM_BASE_URL,
        timeout: float = DEFAULT_OSRM_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def distance_matrix(
        self,
        coordinates: list[tuple[float, float]],
    ) -> list[list[float]]:
        """Compute distance matrix, trying OSRM first with Haversine fallback.

        Coordinates are (lat, lon) pairs. OSRM expects lon,lat order,
        which is handled internally.

        Args:
            coordinates: List of (lat, lon) pairs.

        Returns:
            Square matrix of distances in km.
        """
        if not _use_osrm():
            return haversine_matrix(coordinates)

        try:
            return await self._call_osrm_table(coordinates)
        except OSRMError as e:
            logger.warning("OSRM table request failed: %s, falling back to Haversine", e)
        except asyncio.TimeoutError:
            logger.warning(
                "OSRM table request timed out after %.1fs, falling back to Haversine",
                self.timeout,
            )
        except Exception:
            logger.exception("Unexpected OSRM error, falling back to Haversine")

        return haversine_matrix(coordinates)

    async def _call_osrm_table(
        self,
        coordinates: list[tuple[float, float]],
    ) -> list[list[float]]:
        """Call OSRM /table endpoint and parse the distance matrix.

        OSRM expects coordinates in lon,lat order (GeoJSON convention).
        We receive them as (lat, lon) and reorder.

        API: GET /table/v1/{profile}/{lon1},{lat1};{lon2},{lat2}...?annotations=distance

        Returns:
            Square matrix in km.
        """
        if len(coordinates) < 2:
            # Single coordinate: trivial 1x1 matrix
            return [[0.0]]

        # Convert (lat, lon) to OSRM's lon,lat order
        coord_strings = [f"{lon},{lat}" for lat, lon in coordinates]
        coords_param = ";".join(coord_strings)

        url = f"{self.base_url}/table/v1/driving/{coords_param}"
        params = {"annotations": "distance"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("code") != "Ok":
            message = data.get("message", "Unknown OSRM error")
            raise OSRMError(f"OSRM returned code={data.get('code')}: {message}")

        distances_m = data.get("distances")
        if not distances_m:
            raise OSRMError("OSRM response missing 'distances' field")

        n = len(distances_m)
        if n != len(coordinates):
            raise OSRMError(
                f"OSRM returned {n}x{n} matrix for {len(coordinates)} coordinates"
            )

        # Convert meters → kilometers, replace null with 0.0
        matrix_km: list[list[float]] = []
        for row in distances_m:
            km_row: list[float] = []
            for val in row:
                if val is None:
                    km_row.append(0.0)
                else:
                    km_row.append(float(val) / 1000.0)
            matrix_km.append(km_row)

        logger.debug(
            "OSRM table: %d coordinates, %.1f km max",
            len(coordinates),
            max(max(r) for r in matrix_km),
        )
        return matrix_km

    async def health_check(self) -> bool:
        """Check if OSRM server is reachable and responding.

        Returns:
            True if OSRM returns Ok for a simple route request.
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/route/v1/driving/13.40,52.52;13.41,52.53"
                    "?overview=false"
                )
                response.raise_for_status()
                data = response.json()
                return data.get("code") == "Ok"
        except Exception:
            return False


def _use_osrm() -> bool:
    """Check if OSRM should be used based on environment."""
    return os.environ.get("USE_OSRM", "0") == "1"
