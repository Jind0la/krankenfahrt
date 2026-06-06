"""Dispatch engine — assigns trips to drivers.

Phase 1: Greedy nearest-driver with time window validation.
Phase 2: OR-Tools PDPTW (Pickup and Delivery with Time Windows).
"""

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from krankenfahrt.models.schema import Driver, Trip


# ---------------------------------------------------------------------------
# Domain errors — descriptive, debuggable, production-ready
# ---------------------------------------------------------------------------

class ConstraintKind(str, Enum):
    """Classification of constraint violations for logging and dashboards."""
    VEHICLE_TYPE_MISMATCH = "vehicle_type_mismatch"
    NO_P_SCHEIN = "no_p_schein"
    OUTSIDE_WORK_HOURS = "outside_work_hours"
    WRONG_WORK_DAY = "wrong_work_day"
    DRIVER_INACTIVE = "driver_inactive"
    NO_LOCATION = "no_location"
    TRIP_OVERLAP = "trip_overlap"
    NO_DRIVERS_AVAILABLE = "no_drivers_available"


class ConstraintViolation(Exception):
    """A single constraint that prevented a driver from being assigned.

    These are collected so the dispatch caller can surface every reason a
    particular driver was skipped — critical for debugging "why wasn't Fahrer X
    assigned?" questions from the chef.
    """

    def __init__(self, kind: ConstraintKind, driver_id: int, detail: str) -> None:
        self.kind = kind
        self.driver_id = driver_id
        self.detail = detail
        super().__init__(f"[{kind.value}] Driver {driver_id}: {detail}")


class DispatchError(Exception):
    """Top-level dispatch failure — raised when NO driver can be assigned."""

    def __init__(self, trip_id: int, violations: list[ConstraintViolation]) -> None:
        self.trip_id = trip_id
        self.violations = violations
        summary = "; ".join(str(v) for v in violations)
        super().__init__(f"No driver available for trip {trip_id}: {summary}")


# ---------------------------------------------------------------------------
# Distance calculation
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance in kilometres between two points.

    Handles edge cases:
    - Zero distance (same point) → 0.0
    - Negative coordinates (southern/western hemisphere) — supported
    - Antipodal points — finite result (≈20 037 km)
    - Floating-point safety via clamping asin argument to [-1, 1].
    """
    # Guard: non-finite inputs
    if not all(math.isfinite(v) for v in (lat1, lon1, lat2, lon2)):
        raise ValueError(
            f"haversine_km received non-finite coordinate: "
            f"({lat1}, {lon1}) → ({lat2}, {lon2})"
        )

    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    # Clamp for floating-point noise (e.g. sin² + cos² ≈ 1.0000000000000002)
    a = max(0.0, min(1.0, a))
    return R * 2 * math.asin(math.sqrt(a))


def _driver_position(driver: Driver) -> Optional[tuple[float, float]]:
    """Extract (lat, lon) from a Driver record, or None if unknown."""
    if driver.location_lat is not None and driver.location_lon is not None:
        return (driver.location_lat, driver.location_lon)
    return None


def _pickup_position(trip: Trip) -> Optional[tuple[float, float]]:
    """Extract (lat, lon) from the trip's driver_location fields.

    These fields double as the pickup coordinates in MVP (geocoding is Phase 2).
    """
    if trip.driver_location_lat is not None and trip.driver_location_lon is not None:
        return (trip.driver_location_lat, trip.driver_location_lon)
    return None


# ---------------------------------------------------------------------------
# Greedy dispatch engine
# ---------------------------------------------------------------------------

# Configurable tolerance for overlap checks.
# If a driver's existing trip ends at 10:00 and the new trip starts at 10:05,
# do we consider that an overlap?  With tolerance=5 the answer is YES.
OVERLAP_TOLERANCE_MINUTES: int = 5

# Maps Python weekday (0=Monday, 6=Sunday) → German 2-letter abbreviation.
# strftime("%a") is locale-dependent; this mapping is deterministic.
_WEEKDAY_TO_GERMAN: dict[int, str] = {
    0: "Mo",
    1: "Di",
    2: "Mi",
    3: "Do",
    4: "Fr",
    5: "Sa",
    6: "So",
}
ACTIVE_TRIP_STATUSES: tuple[str, ...] = (
    "zugewiesen",
    "anfahrt",
    "angekommen",
    "patient_an_bord",
    "unterwegs",
)


@dataclass
class Assignment:
    driver: Driver
    trip: Trip
    distance_km: float
    score: float  # lower = better


@dataclass
class OverlapCheckResult:
    """Details about an overlap with an existing trip.

    If `overlaps` is False, the remaining fields are irrelevant.
    """
    overlaps: bool
    conflicting_trip_id: Optional[int] = None
    conflicting_time: Optional[str] = None  # human-readable
    detail: Optional[str] = None


class GreedyDispatchEngine:
    """Nearest-driver assignment with constraint validation and overlap detection.

    This engine is designed to be called from a Tortoise-async context.
    All DB queries go through Tortoise ORM's async interface.
    """

    # ── public API ──────────────────────────────────────────────────────

    async def find_best_driver(
        self,
        trip: Trip,
        available_drivers: list[Driver],
    ) -> Assignment:
        """Find the best driver for *trip* among *available_drivers*.

        Returns:
            Assignment — the best match.

        Raises:
            DispatchError — when no driver passes all constraints.
        """
        violations: list[ConstraintViolation] = []
        best: Optional[Assignment] = None

        for driver in available_drivers:
            driver_violations: list[ConstraintViolation] = []

            # --- constraint gates ---
            await self._check_inactive(driver, driver_violations)
            # Only check further constraints if the driver is active
            if not driver_violations:
                await self._check_vehicle_match(driver, trip, driver_violations)
                await self._check_p_schein(driver, trip, driver_violations)
                await self._check_work_time(driver, trip, driver_violations)
                await self._check_work_day(driver, trip, driver_violations)
                await self._check_overlap(driver, trip, driver_violations)

            if driver_violations:
                violations.extend(driver_violations)
                continue

            # --- distance & scoring ---
            distance = self._compute_distance(driver, trip)

            # Score = pure distance for now (lower is better).
            # Future: factor in load balance, driver preferences, etc.
            score = distance

            if best is None or score < best.score:
                best = Assignment(
                    driver=driver, trip=trip, distance_km=distance, score=score
                )

        if best is None:
            raise DispatchError(trip_id=trip.id, violations=violations)

        return best

    # ── constraint checks — each appends to violations ─────────────────

    async def _check_inactive(
        self, driver: Driver, violations: list[ConstraintViolation]
    ) -> None:
        if not driver.active:
            violations.append(
                ConstraintViolation(
                    ConstraintKind.DRIVER_INACTIVE,
                    driver.id,
                    "Driver is deactivated (active=False)",
                )
            )

    async def _check_vehicle_match(
        self,
        driver: Driver,
        trip: Trip,
        violations: list[ConstraintViolation],
    ) -> None:
        required_type = await self._get_trip_vehicle_type(trip)
        if driver.vehicle is None:
            violations.append(
                ConstraintViolation(
                    ConstraintKind.VEHICLE_TYPE_MISMATCH,
                    driver.id,
                    f"Driver has no vehicle assigned (trip requires {required_type})",
                )
            )
            return
        if driver.vehicle.vehicle_type != required_type:
            violations.append(
                ConstraintViolation(
                    ConstraintKind.VEHICLE_TYPE_MISMATCH,
                    driver.id,
                    f"Vehicle type '{driver.vehicle.vehicle_type}' != required '{required_type}'",
                )
            )

    async def _check_p_schein(
        self,
        driver: Driver,
        trip: Trip,
        violations: list[ConstraintViolation],
    ) -> None:
        if await self._needs_p_schein(trip) and not driver.p_schein:
            violations.append(
                ConstraintViolation(
                    ConstraintKind.NO_P_SCHEIN,
                    driver.id,
                    f"Trip requires Personenbeförderungsschein but driver does not have one",
                )
            )

    async def _check_work_time(
        self,
        driver: Driver,
        trip: Trip,
        violations: list[ConstraintViolation],
    ) -> None:
        pickup_time = trip.scheduled_pickup.time()
        if driver.work_hours_start is None or driver.work_hours_end is None:
            return  # no restriction configured
        if pickup_time < driver.work_hours_start or pickup_time > driver.work_hours_end:
            violations.append(
                ConstraintViolation(
                    ConstraintKind.OUTSIDE_WORK_HOURS,
                    driver.id,
                    f"Pickup {pickup_time} outside work hours "
                    f"[{driver.work_hours_start}–{driver.work_hours_end}]",
                )
            )

    async def _check_work_day(
        self,
        driver: Driver,
        trip: Trip,
        violations: list[ConstraintViolation],
    ) -> None:
        # work_days is a comma-separated German 2-letter abbreviations: "Mo,Di,Mi"
        work_days_raw = driver.work_days or ""
        allowed = {d.strip() for d in work_days_raw.split(",") if d.strip()}
        if not allowed:
            return  # no restriction
        day_name = _WEEKDAY_TO_GERMAN[trip.scheduled_pickup.weekday()]
        if day_name not in allowed:
            violations.append(
                ConstraintViolation(
                    ConstraintKind.WRONG_WORK_DAY,
                    driver.id,
                    f"Pickup day '{day_name}' not in driver work days: {allowed}",
                )
            )

    async def _check_overlap(
        self,
        driver: Driver,
        trip: Trip,
        violations: list[ConstraintViolation],
    ) -> None:
        result = await self._detect_overlap(driver, trip)
        if result.overlaps:
            violations.append(
                ConstraintViolation(
                    ConstraintKind.TRIP_OVERLAP,
                    driver.id,
                    result.detail or f"Conflicts with trip {result.conflicting_trip_id}",
                )
            )

    # ── overlap detection ──────────────────────────────────────────────

    async def _detect_overlap(
        self, driver: Driver, trip: Trip, tolerance_minutes: int | None = None
    ) -> OverlapCheckResult:
        """Check whether *trip* overlaps with any active trip of *driver*.

        Args:
            tolerance_minutes: Buffer added to each end of the time window.
                Defaults to OVERLAP_TOLERANCE_MINUTES (5).

        Returns:
            OverlapCheckResult with details of the first conflict found.
        """
        if tolerance_minutes is None:
            tolerance_minutes = OVERLAP_TOLERANCE_MINUTES

        tolerance = timedelta(minutes=tolerance_minutes)

        # Time window of the proposed trip with tolerance padding
        proposed_start = trip.scheduled_pickup - tolerance
        proposed_end = (
            trip.scheduled_dropoff + tolerance
            if trip.scheduled_dropoff
            else trip.scheduled_pickup + timedelta(hours=1) + tolerance
        )

        # Query active trips for this driver whose time window
        # intersects [proposed_start, proposed_end].
        #
        # Two intervals [A_start, A_end] and [B_start, B_end] overlap iff
        #   A_start < B_end AND B_start < A_end
        from tortoise.expressions import Q

        active_trips = await Trip.filter(
            Q(driver_id=driver.id)
            & Q(status__in=list(ACTIVE_TRIP_STATUSES))
            # existing-trip's scheduled_pickup < proposed_end
            & Q(scheduled_pickup__lt=proposed_end)
        ).all()

        for existing in active_trips:
            existing_start = existing.scheduled_pickup - tolerance
            existing_end = (
                existing.scheduled_dropoff + tolerance
                if existing.scheduled_dropoff
                else existing.scheduled_pickup + timedelta(hours=1) + tolerance
            )

            if proposed_start < existing_end and existing_start < proposed_end:
                return OverlapCheckResult(
                    overlaps=True,
                    conflicting_trip_id=existing.id,
                    conflicting_time=existing.scheduled_pickup.isoformat(),
                    detail=(
                        f"Overlap with trip #{existing.id} "
                        f"({existing.scheduled_pickup.isoformat()}; "
                        f"status={existing.status})"
                    ),
                )

        return OverlapCheckResult(overlaps=False)

    # ── distance ───────────────────────────────────────────────────────

    def _compute_distance(self, driver: Driver, trip: Trip) -> float:
        """Compute Haversine distance from driver to pickup location.

        Edge cases handled:
        - Missing coordinates → returns 0.0 (graceful degradation)
        - Same coordinates → 0.0
        - Negative coordinates → valid calculation
        - Non-finite coordinates → raises ValueError (shouldn't happen with DB floats)
        """
        driver_pos = _driver_position(driver)
        pickup_pos = _pickup_position(trip)

        if driver_pos is None or pickup_pos is None:
            return 0.0  # Not enough data; gracefully degrade

        return haversine_km(
            driver_pos[0], driver_pos[1], pickup_pos[0], pickup_pos[1]
        )

    # ── helpers ────────────────────────────────────────────────────────

    async def _get_trip_vehicle_type(self, trip: Trip) -> str:
        patient = await trip.patient  # Tortoise fetches related object
        return patient.vehicle_type

    async def _needs_p_schein(self, trip: Trip) -> bool:
        patient = await trip.patient
        return patient.vehicle_type in ("Liege", "KTW")
