"""Greedy heuristic for PDVRPTW baseline comparison.

Implements a sequential cheapest-insertion heuristic for the Pickup and Delivery
Vehicle Routing Problem with Time Windows. Designed to produce solutions
in the same RouteOutput format as the OR-Tools solver for direct comparison.

Strategy:
1. Sort trips by pickup time window start (earliest first).
2. For each trip, try to insert its pickup+delivery pair into an existing
   vehicle route at the cheapest feasible position (minimum extra distance).
3. If no insertion is feasible, leave trip unassigned.
4. Apply time window and capacity checks at every insertion step.

This is a classic cheapest-insertion heuristic adapted for PDVRPTW.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from krankenfahrt.routing.models import (
    RouteInput,
    RouteOutput,
    RoutePlan,
    RouteStop,
    VehicleSpec,
)


def _dt_to_min(dt: datetime) -> int:
    """Convert datetime to minutes since midnight of the same day."""
    return dt.hour * 60 + dt.minute


def _min_to_dt(minutes: int, base_date: datetime) -> datetime:
    """Convert minutes-since-midnight back to datetime on base_date."""
    return base_date.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=minutes)


@dataclass
class _RouteState:
    """Internal mutable state for a vehicle route during construction."""

    vehicle_idx: int
    vehicle: VehicleSpec
    stops: list[RouteStop] = field(default_factory=list)
    arrival_minutes: list[int] = field(default_factory=list)
    """Scheduled arrival times in minutes-since-midnight."""

    @property
    def vehicle_id(self) -> int:
        return self.vehicle.vehicle_id

    @property
    def capacity(self) -> int:
        return self.vehicle.capacity

    def can_insert(
        self,
        pickup: RouteStop,
        delivery: RouteStop,
        problem: RouteInput,
    ) -> bool:
        """Check if pickup+delivery pair can be inserted somewhere in this route."""
        n = len(self.stops)
        for p_pos in range(n + 1):
            for d_pos in range(p_pos, n + 1):
                if self._try_insertion(p_pos, d_pos, pickup, delivery, problem)[0] is not None:
                    return True
        return False

    def insert(
        self,
        pickup: RouteStop,
        delivery: RouteStop,
        problem: RouteInput,
    ) -> bool:
        """Insert pickup+delivery at the cheapest feasible position. Returns True on success."""
        n = len(self.stops)
        best_cost = float("inf")
        best_candidate: list[RouteStop] | None = None
        best_arrivals: list[int] | None = None

        for p_pos in range(n + 1):
            for d_pos in range(p_pos, n + 1):
                candidate, arrivals, cost = self._try_insertion(
                    p_pos, d_pos, pickup, delivery, problem
                )
                if candidate is not None and cost < best_cost:
                    best_cost = cost
                    best_candidate = candidate
                    best_arrivals = arrivals

        if best_candidate is not None:
            self.stops = best_candidate
            self.arrival_minutes = best_arrivals
            return True
        return False

    def _try_insertion(
        self,
        p_pos: int,
        d_pos: int,
        pickup: RouteStop,
        delivery: RouteStop,
        problem: RouteInput,
    ) -> tuple[list[RouteStop] | None, list[int] | None, float]:
        """Try inserting pickup at p_pos and delivery at d_pos (relative to original stops).

        Returns (new_stops, new_arrivals, extra_distance_km) or (None, None, inf).
        """
        n = len(self.stops)

        # Build candidate stop order: insert pickup at p_pos, then delivery at d_pos
        # where d_pos is relative to the ORIGINAL stop list (before pickup insertion).
        candidate: list[RouteStop] = []
        for i in range(n):
            if i == p_pos:
                candidate.append(pickup)
            if i == d_pos:
                candidate.append(delivery)
            candidate.append(self.stops[i])
        if p_pos == n:
            candidate.append(pickup)
        if d_pos == n:
            candidate.append(delivery)

        # --- Validate sequentially: time windows + capacity ---
        # Start from depot
        depot_lat = self.vehicle.depot_lat
        depot_lon = self.vehicle.depot_lon
        departure_min = _dt_to_min(self.vehicle.work_start)
        vehicle_end = _dt_to_min(self.vehicle.work_end)

        arrival = departure_min
        prev_lat, prev_lon = depot_lat, depot_lon
        arrivals: list[int] = []
        load = 0
        total_extra_dist = 0.0

        for stop in candidate:
            # Travel from previous location
            dist = _haversine_km(prev_lat, prev_lon, stop.lat, stop.lon)
            travel_min = max(1, int(dist / 30.0 * 60))  # 30 km/h average speed
            total_extra_dist += dist

            arrival = max(arrival + travel_min, _dt_to_min(stop.time_window_start))

            # Check time window end
            if arrival > _dt_to_min(stop.time_window_end):
                return None, None, float("inf")

            # Check vehicle end time
            if arrival > vehicle_end:
                return None, None, float("inf")

            # Check capacity
            load += stop.demand if stop.is_pickup else -stop.demand
            if load > self.capacity:
                return None, None, float("inf")

            arrivals.append(arrival)
            arrival += stop.service_duration_min
            prev_lat, prev_lon = stop.lat, stop.lon

        return candidate, arrivals, total_extra_dist


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    import math

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


class GreedyPDVRPTWSolver:
    """Greedy cheapest-insertion heuristic for PDVRPTW.

    Produces solutions in the same RouteOutput format as OrtoolsPDVRPTWSolver
    for direct comparison of solution quality, runtime, and feasibility.
    """

    def solve(self, problem: RouteInput) -> RouteOutput:
        """Solve a PDVRPTW instance using greedy cheapest insertion.

        Algorithm:
        1. Sort trips by earliest pickup time window.
        2. For each trip, find cheapest feasible insertion across all vehicles.
        3. Insert at best position; if none found, leave unassigned.
        """
        start_time = time.monotonic()

        # Group stops by trip_id and sort by earliest pickup time window
        trips: dict[int, list[RouteStop]] = {}
        for stop in problem.stops:
            trips.setdefault(stop.trip_id, []).append(stop)

        sorted_trips = sorted(
            trips.items(),
            key=lambda item: min(
                _dt_to_min(s.time_window_start)
                for s in item[1]
                if s.is_pickup
            ),
        )

        # Initialize empty routes for each vehicle
        routes: list[_RouteState] = []
        for v_idx, vehicle in enumerate(problem.vehicles):
            routes.append(
                _RouteState(
                    vehicle_idx=v_idx,
                    vehicle=vehicle,
                )
            )

        unassigned: list[int] = []

        for trip_id, stops in sorted_trips:
            pickup = next((s for s in stops if s.is_pickup), None)
            delivery = next((s for s in stops if s.is_delivery), None)

            if pickup is None or delivery is None:
                unassigned.append(trip_id)
                continue

            # Find best insertion across all routes
            best_route_idx = -1
            best_cost = float("inf")

            for r_idx, route in enumerate(routes):
                # Try all positions, find min extra distance
                n = len(route.stops)
                for p_pos in range(n + 1):
                    for d_pos in range(p_pos, n + 1):
                        _, _, cost = route._try_insertion(
                            p_pos, d_pos, pickup, delivery, problem
                        )
                        if cost < best_cost:
                            best_cost = cost
                            best_route_idx = r_idx

            if best_route_idx >= 0:
                routes[best_route_idx].insert(pickup, delivery, problem)
            else:
                unassigned.append(trip_id)

        # --- Build output ---
        output_routes: list[RoutePlan] = []
        total_distance = 0.0
        total_time = 0

        # Determine base date from first stop for datetime reconstruction
        base_date = problem.stops[0].time_window_start if problem.stops else datetime(2024, 6, 15)

        for route_state in routes:
            if not route_state.stops:
                continue

            # Calculate route distance from depot through all stops
            route_dist = 0.0
            depot_lat = route_state.vehicle.depot_lat
            depot_lon = route_state.vehicle.depot_lon
            prev_lat, prev_lon = depot_lat, depot_lon

            for stop in route_state.stops:
                route_dist += _haversine_km(prev_lat, prev_lon, stop.lat, stop.lon)
                prev_lat, prev_lon = stop.lat, stop.lon
            # Add return to depot
            route_dist += _haversine_km(prev_lat, prev_lon, depot_lat, depot_lon)

            route_time = (
                route_state.arrival_minutes[-1]
                - route_state.arrival_minutes[0]
                + route_state.stops[-1].service_duration_min
                if route_state.arrival_minutes
                else 0
            )

            arrival_datetimes = [
                _min_to_dt(m, base_date) for m in route_state.arrival_minutes
            ]

            output_routes.append(
                RoutePlan(
                    vehicle_id=route_state.vehicle_id,
                    stops=route_state.stops,
                    total_distance_km=route_dist,
                    total_time_min=route_time,
                    arrival_times=arrival_datetimes,
                )
            )
            total_distance += route_dist
            total_time += route_time

        solve_time = time.monotonic() - start_time

        return RouteOutput(
            routes=output_routes,
            unassigned_trips=unassigned,
            total_distance_km=total_distance,
            total_time_min=total_time,
            num_vehicles_used=len(output_routes),
            solver_name="greedy",
            solve_time_sec=solve_time,
        )
