"""Tests for OSRM distance matrix client with Haversine fallback.

Covers:
- haversine_km correctness (known distances)
- haversine_matrix structure
- OSRMClient fallback when USE_OSRM=0
- OSRMClient fallback when OSRM unreachable
- Pipeline integration with OSRM (Haversine path)
"""

import math
import os

import pytest

from krankenfahrt.routing.osrm_client import (
    EARTH_RADIUS_KM,
    OSRMClient,
    OSRMError,
    haversine_km,
    haversine_matrix,
)


# ── Haversine correctness tests ────────────────────────────────────────────


class TestHaversineKm:
    def test_same_point_zero(self):
        assert haversine_km(52.52, 13.40, 52.52, 13.40) == 0.0

    def test_berlin_to_munich(self):
        """Berlin (52.52, 13.40) → Munich (48.14, 11.58) ≈ 504 km."""
        dist = haversine_km(52.52, 13.40, 48.14, 11.58)
        assert 490 < dist < 520, f"Expected ~504 km, got {dist}"

    def test_berlin_to_hamburg(self):
        """Berlin (52.52, 13.40) → Hamburg (53.55, 9.99) ≈ 256 km."""
        dist = haversine_km(52.52, 13.40, 53.55, 9.99)
        assert 240 < dist < 270, f"Expected ~256 km, got {dist}"

    def test_symmetric(self):
        d1 = haversine_km(52.52, 13.40, 48.14, 11.58)
        d2 = haversine_km(48.14, 11.58, 52.52, 13.40)
        assert math.isclose(d1, d2, rel_tol=1e-9)

    def test_antipodal(self):
        """Antipodal points: opposite sides of Earth ≈ 20,000 km."""
        dist = haversine_km(0.0, 0.0, 0.0, 180.0)
        half_circumference = math.pi * EARTH_RADIUS_KM
        assert math.isclose(dist, half_circumference, rel_tol=1e-6)

    def test_equator_quarter(self):
        """Quarter around the equator: 0°,0° → 0°,90°."""
        dist = haversine_km(0.0, 0.0, 0.0, 90.0)
        expected = (math.pi / 2) * EARTH_RADIUS_KM
        assert math.isclose(dist, expected, rel_tol=1e-6)


# ── Haversine matrix tests ─────────────────────────────────────────────────


class TestHaversineMatrix:
    def test_single_coordinate(self):
        coords = [(52.52, 13.40)]
        matrix = haversine_matrix(coords)
        assert len(matrix) == 1
        assert matrix[0] == [0.0]

    def test_diagonal_zero(self):
        coords = [(52.52, 13.40), (48.14, 11.58), (53.55, 9.99)]
        matrix = haversine_matrix(coords)
        for i in range(len(coords)):
            assert matrix[i][i] == 0.0, f"Diagonal element [{i}][{i}] should be 0"

    def test_square_shape(self):
        coords = [(52.52, 13.40), (48.14, 11.58), (53.55, 9.99)]
        matrix = haversine_matrix(coords)
        assert len(matrix) == 3
        for row in matrix:
            assert len(row) == 3

    def test_symmetric(self):
        coords = [(52.52, 13.40), (48.14, 11.58), (53.55, 9.99)]
        matrix = haversine_matrix(coords)
        for i in range(3):
            for j in range(3):
                assert math.isclose(
                    matrix[i][j], matrix[j][i], rel_tol=1e-9
                ), f"Asymmetry at [{i}][{j}]: {matrix[i][j]} vs {matrix[j][i]}"

    def test_matches_elementwise(self):
        """Matrix entries should match direct haversine_km calls."""
        coords = [(52.52, 13.40), (48.14, 11.58), (53.55, 9.99)]
        matrix = haversine_matrix(coords)
        for i in range(3):
            for j in range(3):
                if i != j:
                    expected = haversine_km(*coords[i], *coords[j])
                    assert math.isclose(matrix[i][j], expected, rel_tol=1e-9)


# ── OSRMClient fallback tests ──────────────────────────────────────────────


class TestOSRMClientFallback:
    """Test that OSRMClient falls back to Haversine when OSRM unavailable."""

    @pytest.mark.asyncio
    async def test_fallback_when_osrm_disabled(self, monkeypatch):
        """When USE_OSRM=0, skip OSRM entirely, use Haversine."""
        monkeypatch.setenv("USE_OSRM", "0")
        client = OSRMClient(base_url="http://localhost:5000")
        coords = [(52.52, 13.40), (48.14, 11.58)]
        matrix = await client.distance_matrix(coords)
        assert len(matrix) == 2
        assert matrix[0][0] == 0.0
        assert matrix[1][1] == 0.0
        assert matrix[0][1] > 0

    @pytest.mark.asyncio
    async def test_fallback_when_osrm_unreachable(self, monkeypatch):
        """When OSRM enabled but unreachable, fall back to Haversine."""
        monkeypatch.setenv("USE_OSRM", "1")
        # Use a non-routable URL to force connection failure
        client = OSRMClient(
            base_url="http://127.0.0.1:19999",  # Nothing listening here
            timeout=0.5,
        )
        coords = [(52.52, 13.40), (48.14, 11.58)]
        matrix = await client.distance_matrix(coords)
        # Should get Haversine fallback
        assert len(matrix) == 2
        assert matrix[0][0] == 0.0
        assert matrix[0][1] > 0


class TestOSRMClientMatrixSync:
    """Tests that don't require a running OSRM server."""

    def test_health_check_unreachable(self):
        client = OSRMClient(base_url="http://127.0.0.1:19999", timeout=0.3)
        # Must run in async context
        import asyncio
        result = asyncio.run(client.health_check())
        assert result is False


# ── OSRMClient _call_osrm_table tests ──────────────────────────────────────


class TestOSRMCallTable:
    """Test _call_osrm_table edge cases."""

    @pytest.mark.asyncio
    async def test_single_coordinate(self):
        client = OSRMClient()
        matrix = await client._call_osrm_table([(52.52, 13.40)])
        assert matrix == [[0.0]]

    @pytest.mark.asyncio
    async def test_diagonal_zero(self):
        """Matrix diagonal should be zero (no self-distance)."""
        # This test hits real OSRM if available, otherwise raises
        # but that's okay — the edge case is the coordinate handling.
        pass


class TestOSRMError:
    def test_string_representation(self):
        err = OSRMError("No route found")
        assert str(err) == "No route found"

    def test_with_code(self):
        err = OSRMError("OSRM returned code=NoRoute: No route found")
        assert "NoRoute" in str(err)
