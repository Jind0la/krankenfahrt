"""Dispatch engine — assigns trips to drivers.

Phase 1: Greedy nearest-driver with time window validation.
Phase 2: OR-Tools PDPTW (Pickup and Delivery with Time Windows).
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from krankenfahrt.models.schema import Driver, Trip


@dataclass
class Assignment:
    driver: Driver
    trip: Trip
    distance_km: float  # Haversine or OSRM distance
    score: float  # Lower is better


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance in kilometers."""
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


class GreedyDispatchEngine:
    """Simple nearest-driver assignment with basic constraints."""

    async def find_best_driver(
        self,
        trip: Trip,
        available_drivers: list[Driver],
    ) -> Optional[Assignment]:
        """Find the best driver for a single trip."""
        best: Optional[Assignment] = None

        for driver in available_drivers:
            # 1. Vehicle type match
            if driver.vehicle and driver.vehicle.vehicle_type != (
                await self._get_trip_vehicle_type(trip)
            ):
                continue

            # 2. P-Schein check (if KTW/Liege transport)
            if await self._needs_p_schein(trip) and not driver.p_schein:
                continue

            # 3. Availability check (working hours, no overlapping trips)
            if not await self._is_available(driver, trip):
                continue

            # 4. Distance — simplified: use driver's last known location
            # In production: get from trip/vehicle GPS or OSRM
            distance = self._estimate_distance(driver, trip)

            score = distance  # Can factor in load balance, preferences later

            if best is None or score < best.score:
                best = Assignment(driver=driver, trip=trip, distance_km=distance, score=score)

        return best

    def _estimate_distance(self, driver: Driver, trip: Trip) -> float:
        """Estimate distance from driver to pickup location.
        
        In MVP: return 0 (assume equal distance for all drivers).
        Phase 2: Use OSRM distance matrix or driver's last GPS position.
        """
        return 0.0

    async def _get_trip_vehicle_type(self, trip: Trip) -> str:
        patient = await trip.patient
        return patient.vehicle_type

    async def _needs_p_schein(self, trip: Trip) -> bool:
        """Check if trip requires Personenbeförderungsschein."""
        patient = await trip.patient
        return patient.vehicle_type in ("Liege", "KTW")

    async def _is_available(self, driver: Driver, trip: Trip) -> bool:
        """Check if driver is available for the trip time window."""
        if not driver.active:
            return False

        # Check work hours
        pickup_time = trip.scheduled_pickup.time()
        if pickup_time < driver.work_hours_start or pickup_time > driver.work_hours_end:
            return False

        # Check work days
        day_name = trip.scheduled_pickup.strftime("%a")[:2]  # "Mo", "Di", etc.
        if day_name not in driver.work_days:
            return False

        # TODO: Check for overlapping trips (query DB)
        return True
