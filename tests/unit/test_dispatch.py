"""Tests for the production-ready GreedyDispatchEngine.

Covers three feature domains:
  1. Distance calculation — haversine edge cases
  2. Constraint checking  — every gate with descriptive errors
  3. Overlap detection    — configurable tolerance, boundary scenarios
"""

import asyncio
import math
from datetime import datetime, time, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the SUT with test-safe env defaults
# ---------------------------------------------------------------------------
import os

os.environ.setdefault("PATIENT_BOT_TOKEN", "test_patient_token")
os.environ.setdefault("DRIVER_BOT_TOKEN", "test_driver_token")
os.environ.setdefault("CHEF_BOT_TOKEN", "test_chef_token")
os.environ.setdefault("DEEPSEEK_API_KEY", "test_deepseek_key")

from krankenfahrt.core.dispatch import (  # noqa: E402
    ACTIVE_TRIP_STATUSES,
    OVERLAP_TOLERANCE_MINUTES,
    Assignment,
    ConstraintKind,
    ConstraintViolation,
    DispatchError,
    GreedyDispatchEngine,
    OverlapCheckResult,
    haversine_km,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. DISTANCE TESTS — pure function, no DB needed
# ═══════════════════════════════════════════════════════════════════════

class TestHaversine:
    """Great-circle distance: correctness and edge cases."""

    # ── normal cases ──

    def test_same_point_returns_zero(self):
        """Distance from a point to itself is 0.0 km."""
        assert haversine_km(52.52, 13.405, 52.52, 13.405) == 0.0

    def test_known_distance_berlin_paris(self):
        """Berlin → Paris ≈ 878 km (within 2%)."""
        d = haversine_km(52.52, 13.405, 48.8566, 2.3522)
        assert 860 < d < 896, f"Expected ~878 km, got {d}"

    def test_known_distance_sydney_london(self):
        """Sydney → London ≈ 16 989 km."""
        d = haversine_km(-33.8688, 151.2093, 51.5074, -0.1278)
        assert 16000 < d < 18000, f"Expected ~16989 km, got {d}"

    # ── edge cases ──

    def test_zero_coordinates(self):
        """Origin (0,0) to (0,0) is zero."""
        assert haversine_km(0.0, 0.0, 0.0, 0.0) == 0.0

    def test_negative_latitude_south(self):
        """Southern hemisphere: Santiago (-33°) to Lima (-12°). ~2460 km."""
        d = haversine_km(-33.4489, -70.6693, -12.0464, -77.0428)
        assert 2200 < d < 2700, f"Expected ~2460 km, got {d}"

    def test_negative_longitude_west(self):
        """Western hemisphere: NYC (-74°) to LA (-118°). ~3940 km."""
        d = haversine_km(40.7128, -74.0060, 34.0522, -118.2437)
        assert 3700 < d < 4200, f"Expected ~3940 km, got {d}"

    def test_antipodal_points_finite(self):
        """Antipodal (opposite sides of Earth) ~20 037 km.

        (0,0) → (0,180) are nearly antipodal; exact antipodes are
        (lat, lon) → (-lat, lon+180).
        """
        d = haversine_km(0.0, 0.0, 0.0, 180.0)
        assert d < 20038 and math.isfinite(d), f"Expected finite, got {d}"

    def test_very_small_distance(self):
        """Points 1 metre apart return ~0.001 km."""
        # 1° ≈ 111.32 km, so 0.00001° ≈ 1.1 m
        d = haversine_km(52.52, 13.405, 52.52001, 13.405)
        assert 0.0 < d < 0.01, f"Expected ~0.001 km, got {d}"

    def test_north_pole_to_south_pole(self):
        """NP (90,0) → SP (-90,0) = 20 004 km (half circumference)."""
        d = haversine_km(90.0, 0.0, -90.0, 0.0)
        assert 19950 < d < 20050, f"Expected ~20004 km, got {d}"

    # ── error cases ──

    def test_nan_raises_valueerror(self):
        with pytest.raises(ValueError, match="non-finite"):
            haversine_km(math.nan, 0.0, 0.0, 0.0)

    def test_inf_raises_valueerror(self):
        with pytest.raises(ValueError, match="non-finite"):
            haversine_km(0.0, 0.0, math.inf, 0.0)

    def test_negative_inf_raises_valueerror(self):
        with pytest.raises(ValueError, match="non-finite"):
            haversine_km(0.0, -math.inf, 0.0, 0.0)

    # ── symmetry ──

    def test_symmetry(self):
        """haversine(A, B) == haversine(B, A)."""
        a = haversine_km(48.1374, 11.5755, 53.5511, 9.9937)
        b = haversine_km(53.5511, 9.9937, 48.1374, 11.5755)
        assert abs(a - b) < 0.001


# ═══════════════════════════════════════════════════════════════════════
# 2. CONSTRAINT VIOLATION TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestConstraintViolation:
    """ConstraintViolation and DispatchError objects are self-documenting."""

    def test_violation_has_kind_driver_detail(self):
        v = ConstraintViolation(
            ConstraintKind.NO_P_SCHEIN, driver_id=7, detail="Missing P-Schein"
        )
        assert v.kind == ConstraintKind.NO_P_SCHEIN
        assert v.driver_id == 7
        assert "P-Schein" in v.detail
        assert "[no_p_schein]" in str(v)
        assert "Driver 7" in str(v)

    def test_dispatch_error_aggregates_violations(self):
        v1 = ConstraintViolation(ConstraintKind.DRIVER_INACTIVE, 1, "Inactive")
        v2 = ConstraintViolation(ConstraintKind.WRONG_WORK_DAY, 2, "Wrong day")
        err = DispatchError(trip_id=42, violations=[v1, v2])

        assert err.trip_id == 42
        assert len(err.violations) == 2
        assert "trip 42" in str(err)
        assert "Inactive" in str(err)
        assert "Wrong day" in str(err)

    def test_all_constraint_kinds_exist(self):
        """Every constraint gate must have a corresponding ConstraintKind."""
        kinds = {k.value for k in ConstraintKind}
        expected = {
            "vehicle_type_mismatch",
            "no_p_schein",
            "outside_work_hours",
            "wrong_work_day",
            "driver_inactive",
            "no_location",
            "trip_overlap",
            "no_drivers_available",
        }
        assert kinds == expected


# ═══════════════════════════════════════════════════════════════════════
# 3. ENGINE DISTANCE TESTS — unit-testable without DB
# ═══════════════════════════════════════════════════════════════════════

class TestEngineDistance:
    """_compute_distance uses haversine when coordinates exist."""

    def test_no_coordinates_returns_zero(self):
        """When driver or trip lacks coordinates, gracefully return 0."""
        engine = GreedyDispatchEngine()
        driver = Mock(location_lat=None, location_lon=None)
        trip = Mock(driver_location_lat=None, driver_location_lon=None)
        assert engine._compute_distance(driver, trip) == 0.0

    def test_driver_has_coords_trip_does_not(self):
        engine = GreedyDispatchEngine()
        driver = Mock(location_lat=52.52, location_lon=13.405)
        trip = Mock(driver_location_lat=None, driver_location_lon=None)
        assert engine._compute_distance(driver, trip) == 0.0

    def test_both_have_coords_returns_positive_distance(self):
        engine = GreedyDispatchEngine()
        driver = Mock(location_lat=52.52, location_lon=13.405)
        trip = Mock(driver_location_lat=48.8566, driver_location_lon=2.3522)
        d = engine._compute_distance(driver, trip)
        assert 860 < d < 896, f"Berlin→Paris should be ~878 km, got {d}"

    def test_same_coords_returns_zero(self):
        engine = GreedyDispatchEngine()
        driver = Mock(location_lat=50.0, location_lon=8.0)
        trip = Mock(driver_location_lat=50.0, driver_location_lon=8.0)
        assert engine._compute_distance(driver, trip) == 0.0


# ═══════════════════════════════════════════════════════════════════════
# 4. OVERLAP DETECTION TESTS — pure logic tests
# ═══════════════════════════════════════════════════════════════════════

class TestOverlapLogic:
    """Two intervals [A_start, A_end] and [B_start, B_end] overlap iff
        A_start < B_end AND B_start < A_end"""

    def intervals_overlap(self, start_a, end_a, start_b, end_b):
        return start_a < end_b and start_b < end_a

    def test_exact_same_time_overlaps(self):
        # 10:00–11:00 vs 10:00–11:00
        assert self.intervals_overlap(10, 11, 10, 11) is True

    def test_contained_overlaps(self):
        # 10:00–12:00 contains 10:30–11:30
        assert self.intervals_overlap(10, 12, 10.5, 11.5) is True

    def test_partial_overlap_tail(self):
        # 10:00–11:00 and 10:30–11:30
        assert self.intervals_overlap(10, 11, 10.5, 11.5) is True

    def test_partial_overlap_head(self):
        # 10:00–11:00 and 9:30–10:30
        assert self.intervals_overlap(10, 11, 9.5, 10.5) is True

    def test_abutting_no_overlap(self):
        # 10:00–11:00 and 11:00–12:00 — end of A == start of B
        assert self.intervals_overlap(10, 11, 11, 12) is False

    def test_separated_no_overlap(self):
        # 10:00–11:00 and 12:00–13:00
        assert self.intervals_overlap(10, 11, 12, 13) is False

    def test_before_no_overlap(self):
        # 8:00–9:00 before 10:00–11:00
        assert self.intervals_overlap(8, 9, 10, 11) is False

    def test_after_no_overlap(self):
        # 14:00–15:00 after 10:00–11:00
        assert self.intervals_overlap(14, 15, 10, 11) is False

    def test_with_tolerance_abutting_becomes_overlap(self):
        """With 5 min tolerance, 10:00–11:00 and 11:00–12:00 overlap
        because proposed_end (11:00+5min) == 11:05 > existing_start (11:00).
        """
        tol = 5 / 60  # 5 minutes in hours
        proposed_start = 10.0 - tol
        proposed_end = 11.0 + tol
        existing_start = 11.0 - tol
        existing_end = 12.0 + tol
        assert self.intervals_overlap(proposed_start, proposed_end, existing_start, existing_end) is True

    def test_tolerance_just_enough(self):
        """With 5 min tolerance, a gap of 11+ min should NOT overlap.

        Proposed: 10:00–10:49, Existing: 11:00–12:00 → gap = 11 min.
        proposed_end  (10:49 + 5 = 10:54)
        existing_start (11:00 - 5 = 10:55)
        10:54 < 10:55 is False → no overlap.

        Using 49 min instead of 50 to avoid floating-point rounding
        making 50/60 + 5/60 appear slightly larger than 55/60.
        """
        tol = 5 / 60
        proposed_start = 10.0 - tol
        proposed_end = (10.0 + 49 / 60) + tol  # 10:49 + 5min = 10:54
        existing_start = 11.0 - tol  # 11:00 - 5min = 10:55
        existing_end = 12.0 + tol
        assert self.intervals_overlap(proposed_start, proposed_end, existing_start, existing_end) is False


# ═══════════════════════════════════════════════════════════════════════
# 5. ENGINE OVERLAP DETECTION — async DB tests
# ═══════════════════════════════════════════════════════════════════════

class TestEngineOverlapDetection:
    """_detect_overlap queries the DB; test with mocking."""

    @pytest.fixture
    def engine(self):
        return GreedyDispatchEngine()

    def make_trip(self, **kwargs):
        """Factory for Trip mocks with sensible defaults."""
        defaults = dict(
            id=1,
            scheduled_pickup=datetime(2026, 6, 10, 10, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 0),
            status="geplant",
            driver_id=None,
        )
        defaults.update(kwargs)
        return Mock(**defaults)

    @pytest.mark.asyncio
    async def test_no_active_trips_returns_no_overlap(self, engine):
        driver = Mock(id=5)
        trip = self.make_trip()

        # Mock Trip.filter().all() → empty list
        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(return_value=[])
            result = await engine._detect_overlap(driver, trip)
            assert result.overlaps is False

    @pytest.mark.asyncio
    async def test_exact_overlap_returns_true(self, engine):
        driver = Mock(id=5)
        trip = self.make_trip(
            id=100,
            scheduled_pickup=datetime(2026, 6, 10, 10, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 0),
        )

        existing = self.make_trip(
            id=50,
            scheduled_pickup=datetime(2026, 6, 10, 10, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 0),
            status="zugewiesen",
        )

        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(return_value=[existing])
            result = await engine._detect_overlap(driver, trip)
            assert result.overlaps is True
            assert result.conflicting_trip_id == 50
            assert "trip #50" in result.detail

    @pytest.mark.asyncio
    async def test_partial_overlap_returns_true(self, engine):
        driver = Mock(id=5)
        # Proposed: 10:00–11:00, Existing: 10:30–11:30
        trip = self.make_trip(
            id=100,
            scheduled_pickup=datetime(2026, 6, 10, 10, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 0),
        )
        existing = self.make_trip(
            id=51,
            scheduled_pickup=datetime(2026, 6, 10, 10, 30),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 30),
            status="anfahrt",
        )

        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(return_value=[existing])
            result = await engine._detect_overlap(driver, trip)
            assert result.overlaps is True
            assert result.conflicting_trip_id == 51

    @pytest.mark.asyncio
    async def test_no_overlap_when_before(self, engine):
        driver = Mock(id=5)
        # Proposed: 13:00–14:00, Existing: 10:00–11:00
        trip = self.make_trip(
            id=100,
            scheduled_pickup=datetime(2026, 6, 10, 13, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 14, 0),
        )
        existing = self.make_trip(
            id=52,
            scheduled_pickup=datetime(2026, 6, 10, 10, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 0),
            status="zugewiesen",
        )

        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(return_value=[existing])
            result = await engine._detect_overlap(driver, trip)
            assert result.overlaps is False

    @pytest.mark.asyncio
    async def test_no_overlap_when_after(self, engine):
        driver = Mock(id=5)
        # Proposed: 8:00–9:00, Existing: 10:00–11:00
        trip = self.make_trip(
            id=100,
            scheduled_pickup=datetime(2026, 6, 10, 8, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 9, 0),
        )
        existing = self.make_trip(
            id=53,
            scheduled_pickup=datetime(2026, 6, 10, 10, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 0),
            status="zugewiesen",
        )

        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(return_value=[existing])
            result = await engine._detect_overlap(driver, trip)
            assert result.overlaps is False

    @pytest.mark.asyncio
    async def test_abutting_with_tolerance_overlaps(self, engine):
        """With default 5-min tolerance, 10:00–11:00 abutting 11:00–12:00
        should overlap because the tolerance window bridges the gap."""
        driver = Mock(id=5)
        # Proposed: 10:00–11:00, Existing: 11:00–12:00 — abutting
        trip = self.make_trip(
            id=100,
            scheduled_pickup=datetime(2026, 6, 10, 10, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 0),
        )
        existing = self.make_trip(
            id=54,
            scheduled_pickup=datetime(2026, 6, 10, 11, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 12, 0),
            status="zugewiesen",
        )

        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(return_value=[existing])
            result = await engine._detect_overlap(driver, trip)
            # With tolerance=5, proposed_end=11:05 > existing_start=10:55 → overlap
            assert result.overlaps is True

    @pytest.mark.asyncio
    async def test_tolerance_exactly_0_no_abutting_overlap(self, engine):
        """With tolerance=0, abutting trips should NOT overlap."""
        driver = Mock(id=5)
        trip = self.make_trip(
            id=100,
            scheduled_pickup=datetime(2026, 6, 10, 10, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 0),
        )
        existing = self.make_trip(
            id=55,
            scheduled_pickup=datetime(2026, 6, 10, 11, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 12, 0),
            status="zugewiesen",
        )

        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(return_value=[existing])
            result = await engine._detect_overlap(driver, trip, tolerance_minutes=0)
            assert result.overlaps is False

    @pytest.mark.asyncio
    async def test_custom_tolerance_30_minutes(self, engine):
        """Large tolerance (30 min) makes a 25-min gap overlap."""
        driver = Mock(id=5)
        # Proposed: 10:00–10:30, Existing: 10:55–11:30 (gap=25 min, tol=30)
        trip = self.make_trip(
            id=100,
            scheduled_pickup=datetime(2026, 6, 10, 10, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 10, 30),
        )
        existing = self.make_trip(
            id=56,
            scheduled_pickup=datetime(2026, 6, 10, 10, 55),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 30),
            status="zugewiesen",
        )

        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(return_value=[existing])
            result = await engine._detect_overlap(driver, trip, tolerance_minutes=30)
            assert result.overlaps is True

    @pytest.mark.asyncio
    async def test_missing_dropoff_uses_default_one_hour(self, engine):
        """When scheduled_dropoff is None, the engine assumes a 1-hour trip."""
        driver = Mock(id=5)
        # Proposed: 10:00 with no dropoff → effective end = 11:00
        trip = self.make_trip(
            id=100,
            scheduled_pickup=datetime(2026, 6, 10, 10, 0),
            scheduled_dropoff=None,
        )
        existing = self.make_trip(
            id=57,
            scheduled_pickup=datetime(2026, 6, 10, 10, 30),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 30),
            status="zugewiesen",
        )

        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(return_value=[existing])
            result = await engine._detect_overlap(driver, trip)
            # proposed end (11:00+tol) > existing start (10:30-tol) → overlap
            assert result.overlaps is True

    @pytest.mark.asyncio
    async def test_overlap_with_multiple_existing_trips(self, engine):
        """Only the first overlap is reported."""
        driver = Mock(id=5)
        trip = self.make_trip(
            id=100,
            scheduled_pickup=datetime(2026, 6, 10, 10, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 0),
        )
        existing1 = self.make_trip(id=58,
            scheduled_pickup=datetime(2026, 6, 10, 9, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 9, 30),
            status="abgeschlossen",  # NOT active — should be filtered
        )
        existing2 = self.make_trip(id=59,
            scheduled_pickup=datetime(2026, 6, 10, 10, 30),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 30),
            status="zugewiesen",  # active and overlapping
        )
        existing3 = self.make_trip(id=60,
            scheduled_pickup=datetime(2026, 6, 10, 10, 45),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 45),
            status="anfahrt",  # also active
        )

        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(
                return_value=[existing1, existing2, existing3]
            )
            result = await engine._detect_overlap(driver, trip)
            assert result.overlaps is True
            # First conflict should be existing2 (id=59)
            assert result.conflicting_trip_id == 59


# ═══════════════════════════════════════════════════════════════════════
# 6. ENGINE CONSTRAINT GATE TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestConstraintGates:
    """Each constraint gate appends a descriptive ConstraintViolation."""

    @pytest.fixture
    def engine(self):
        return GreedyDispatchEngine()

    @pytest.mark.asyncio
    async def test_inactive_driver_gets_violation(self, engine):
        driver = Mock(id=1, active=False)
        violations: list = []
        await engine._check_inactive(driver, violations)
        assert len(violations) == 1
        assert violations[0].kind == ConstraintKind.DRIVER_INACTIVE

    @pytest.mark.asyncio
    async def test_active_driver_no_violation(self, engine):
        driver = Mock(id=2, active=True)
        violations: list = []
        await engine._check_inactive(driver, violations)
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_p_schein_missing_for_ktw(self, engine):
        driver = Mock(id=3, p_schein=False)
        trip = Mock()
        patient = Mock(vehicle_type="KTW")
        trip.patient = patient

        with patch.object(engine, "_needs_p_schein", return_value=True):
            violations: list = []
            await engine._check_p_schein(driver, trip, violations)
            assert len(violations) == 1
            assert violations[0].kind == ConstraintKind.NO_P_SCHEIN

    @pytest.mark.asyncio
    async def test_p_schein_present_no_violation(self, engine):
        driver = Mock(id=4, p_schein=True)
        trip = Mock()
        patient = Mock(vehicle_type="KTW")
        trip.patient = patient

        with patch.object(engine, "_needs_p_schein", return_value=True):
            violations: list = []
            await engine._check_p_schein(driver, trip, violations)
            assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_outside_work_hours_violation(self, engine):
        """Pickup at 18:00 when driver works 07:00–16:00."""
        driver = Mock(id=5, work_hours_start=time(7, 0), work_hours_end=time(16, 0))
        trip = Mock(scheduled_pickup=datetime(2026, 6, 10, 18, 0))
        violations: list = []
        await engine._check_work_time(driver, trip, violations)
        assert len(violations) == 1
        assert violations[0].kind == ConstraintKind.OUTSIDE_WORK_HOURS
        assert "18:00" in violations[0].detail

    @pytest.mark.asyncio
    async def test_within_work_hours_no_violation(self, engine):
        driver = Mock(id=6, work_hours_start=time(7, 0), work_hours_end=time(16, 0))
        trip = Mock(scheduled_pickup=datetime(2026, 6, 10, 10, 0))
        violations: list = []
        await engine._check_work_time(driver, trip, violations)
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_exact_work_hours_boundary_start(self, engine):
        """Pickup exactly at work_hours_start should be valid."""
        driver = Mock(id=7, work_hours_start=time(7, 0), work_hours_end=time(16, 0))
        trip = Mock(scheduled_pickup=datetime(2026, 6, 10, 7, 0))
        violations: list = []
        await engine._check_work_time(driver, trip, violations)
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_exact_work_hours_boundary_end(self, engine):
        """Pickup exactly at work_hours_end should be valid."""
        driver = Mock(id=8, work_hours_start=time(7, 0), work_hours_end=time(16, 0))
        trip = Mock(scheduled_pickup=datetime(2026, 6, 10, 16, 0))
        violations: list = []
        await engine._check_work_time(driver, trip, violations)
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_wrong_work_day_violation(self, engine):
        """Pickup on Saturday but driver works Mon-Fri."""
        # 2026-06-13 is a Saturday
        driver = Mock(id=9, work_days="Mo,Di,Mi,Do,Fr")
        trip = Mock(scheduled_pickup=datetime(2026, 6, 13, 10, 0))
        violations: list = []
        await engine._check_work_day(driver, trip, violations)
        assert len(violations) == 1
        assert violations[0].kind == ConstraintKind.WRONG_WORK_DAY
        assert "Sa" in violations[0].detail

    @pytest.mark.asyncio
    async def test_correct_work_day_no_violation(self, engine):
        """Pickup on Wednesday, driver works Mon-Fri."""
        # 2026-06-10 is a Wednesday
        driver = Mock(id=10, work_days="Mo,Di,Mi,Do,Fr")
        trip = Mock(scheduled_pickup=datetime(2026, 6, 10, 10, 0))
        violations: list = []
        await engine._check_work_day(driver, trip, violations)
        assert len(violations) == 0

    @pytest.mark.asyncio
    async def test_empty_work_days_no_restriction(self, engine):
        """Empty work_days means no restriction."""
        driver = Mock(id=11, work_days="")
        trip = Mock(scheduled_pickup=datetime(2026, 6, 10, 10, 0))
        violations: list = []
        await engine._check_work_day(driver, trip, violations)
        assert len(violations) == 0


# ═══════════════════════════════════════════════════════════════════════
# 7. FULL find_best_driver INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestFindBestDriver:
    """End-to-end dispatch flow with mocked DB."""

    @pytest.fixture
    def engine(self):
        return GreedyDispatchEngine()

    @pytest.fixture
    def trip(self):
        """A realistic trip fixture."""
        patient = Mock(vehicle_type="Sitz")
        trip = Mock(
            id=42,
            scheduled_pickup=datetime(2026, 6, 10, 10, 0),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 0),
            driver_location_lat=50.0,
            driver_location_lon=8.0,
            patient=patient,
        )
        return trip

    def make_driver(self, id, **kwargs):
        """A realistic driver fixture."""
        defaults = dict(
            id=id,
            active=True,
            p_schein=False,
            work_hours_start=time(7, 0),
            work_hours_end=time(16, 0),
            work_days="Mo,Di,Mi,Do,Fr",
            location_lat=49.0,
            location_lon=8.5,
        )
        defaults.update(kwargs)
        driver = Mock(**defaults)
        driver.vehicle = Mock(vehicle_type="Sitz")
        return driver

    @pytest.mark.asyncio
    async def test_single_driver_passes_all_constraints(self, engine, trip):
        driver = self.make_driver(1)

        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(return_value=[])

            # Mock _needs_p_schein to return False (Sitz transport)
            with patch.object(engine, "_needs_p_schein", return_value=False):
                # Mock _get_trip_vehicle_type
                with patch.object(engine, "_get_trip_vehicle_type", return_value="Sitz"):
                    result = await engine.find_best_driver(trip, [driver])

                    assert result.driver.id == 1
                    assert result.trip.id == 42
                    assert result.distance_km > 0  # different coords

    @pytest.mark.asyncio
    async def test_no_drivers_passes_raises_dispatch_error(self, engine, trip):
        """When all drivers fail constraints, DispatchError is raised."""
        driver = self.make_driver(1, active=False)  # inactive → blocked

        with pytest.raises(DispatchError) as exc_info:
            await engine.find_best_driver(trip, [driver])

        assert exc_info.value.trip_id == 42
        assert len(exc_info.value.violations) == 1
        assert exc_info.value.violations[0].kind == ConstraintKind.DRIVER_INACTIVE

    @pytest.mark.asyncio
    async def test_multiple_drivers_picks_closest(self, engine, trip):
        """When multiple drivers pass, the closest one is chosen."""
        # Driver 1: at (52.0, 13.0) — far from pickup (50.0, 8.0)
        driver1 = self.make_driver(1, location_lat=52.0, location_lon=13.0)

        # Driver 2: at (50.1, 8.1) — very close to pickup (50.0, 8.0)
        driver2 = self.make_driver(2, location_lat=50.1, location_lon=8.1)

        # Driver 3: at (48.0, 7.0) — medium distance from pickup
        driver3 = self.make_driver(3, location_lat=48.0, location_lon=7.0)

        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(return_value=[])

            with patch.object(engine, "_needs_p_schein", return_value=False):
                with patch.object(engine, "_get_trip_vehicle_type", return_value="Sitz"):
                    result = await engine.find_best_driver(trip, [driver1, driver2, driver3])

                    assert result.driver.id == 2  # closest driver
                    assert result.distance_km < 50  # should be quite short

    @pytest.mark.asyncio
    async def test_violations_collected_for_all_blocked_drivers(self, engine, trip):
        """When NO driver passes, all violations are collected across drivers.

        Note: the overlap mock returns the same conflicting trip for every
        driver-id query, so any active driver that reaches the overlap gate
        will also get a TRIP_OVERLAP violation on top of their own issue.
        """
        driver1 = self.make_driver(1, active=False)  # inactive
        driver2 = self.make_driver(2, work_days="Mo,Di")  # wrong day + overlap
        driver3 = self.make_driver(3, p_schein=False)
        driver3.vehicle = Mock(vehicle_type="Sitz")  # vehicle matches…

        # …but the overlap mock returns a conflict for any driver
        existing = Mock(
            id=99,
            scheduled_pickup=datetime(2026, 6, 10, 10, 30),
            scheduled_dropoff=datetime(2026, 6, 10, 11, 30),
            status="zugewiesen",
        )

        with patch("krankenfahrt.core.dispatch.Trip") as MockTrip:
            MockTrip.filter.return_value.all = AsyncMock(return_value=[existing])

            with patch.object(engine, "_needs_p_schein", return_value=False):
                with patch.object(engine, "_get_trip_vehicle_type", return_value="Sitz"):
                    with pytest.raises(DispatchError) as exc_info:
                        await engine.find_best_driver(trip, [driver1, driver2, driver3])

                    violations = exc_info.value.violations
                    kinds = {v.kind for v in violations}
                    assert ConstraintKind.DRIVER_INACTIVE in kinds
                    assert ConstraintKind.WRONG_WORK_DAY in kinds
                    assert ConstraintKind.TRIP_OVERLAP in kinds
                    # driver1: inactive (1), driver2: wrong_day + overlap (2), driver3: overlap (1)
                    assert len(violations) == 4


# ═══════════════════════════════════════════════════════════════════════
# 8. CONFIGURATION / CONSTANTS TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestConfiguration:
    def test_overlap_tolerance_is_positive(self):
        assert OVERLAP_TOLERANCE_MINUTES >= 0

    def test_active_trip_statuses_excludes_completed(self):
        assert "abgeschlossen" not in ACTIVE_TRIP_STATUSES
        assert "storniert" not in ACTIVE_TRIP_STATUSES
        assert "problem" not in ACTIVE_TRIP_STATUSES
        assert "geplant" not in ACTIVE_TRIP_STATUSES  # not yet assigned

    def test_active_trip_statuses_includes_all_active(self):
        assert "zugewiesen" in ACTIVE_TRIP_STATUSES
        assert "anfahrt" in ACTIVE_TRIP_STATUSES
        assert "angekommen" in ACTIVE_TRIP_STATUSES
        assert "patient_an_bord" in ACTIVE_TRIP_STATUSES
        assert "unterwegs" in ACTIVE_TRIP_STATUSES

    def test_assignment_dataclass(self):
        """Assignment is just a data holder."""
        driver = Mock(id=1)
        trip = Mock(id=2)
        a = Assignment(driver=driver, trip=trip, distance_km=5.2, score=5.2)
        assert a.driver.id == 1
        assert a.trip.id == 2
        assert a.distance_km == 5.2
        assert a.score == 5.2

    def test_overlap_check_result_defaults(self):
        r = OverlapCheckResult(overlaps=False)
        assert r.overlaps is False
        assert r.conflicting_trip_id is None
