"""Google OR-Tools PDVRPTW solver.

Implements Pickup and Delivery Vehicle Routing with Time Windows
using OR-Tools Routing Library. Supports multiple periods via
single composite instance with day-separated time windows.

Architecture:
- Modeled as PDPTW with pickup/delivery pairs
- Each trip = one pickup + one delivery node
- Time windows enforce scheduled times
- Vehicle capacity limits simultaneous passengers
- Distance matrix uses Haversine or precomputed distances
"""

import time
from datetime import datetime, timedelta

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from krankenfahrt.routing.models import (
    RouteInput,
    RouteOutput,
    RoutePlan,
    RouteStop,
)


class OrtoolsPDVRPTWSolver:
    """PDVRPTW solver using Google OR-Tools Routing Library.

    Models the problem as a PDPTW with:
    - Pickup-delivery pairs (one trip = two stops)
    - Time windows per stop
    - Vehicle capacity constraints
    - Distance matrix

    Time windows are converted to integer minutes relative to midnight
    of the optimization day (auto-detected from first stop's time window).

    Usage:
        solver = OrtoolsPDVRPTWSolver(time_limit_sec=30)
        input_data = RouteInput(stops=..., vehicles=..., ...)
        output = solver.solve(input_data)
    """

    def __init__(self, time_limit_sec: int = 30):
        self.time_limit_sec = time_limit_sec
        self._day_midnight: datetime | None = None

    def _dt_to_min(self, dt: datetime) -> int:
        """Convert datetime to minutes from midnight of the optimization day."""
        if self._day_midnight is None:
            self._day_midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return int((dt - self._day_midnight).total_seconds() / 60)

    def _min_to_dt(self, minutes: int) -> datetime:
        """Convert minutes-from-midnight back to datetime."""
        if self._day_midnight is None:
            self._day_midnight = datetime(2024, 6, 15, 0, 0)
        return self._day_midnight + timedelta(minutes=minutes)

    def solve(self, problem: RouteInput) -> RouteOutput:
        """Solve a PDVRPTW instance.

        Args:
            problem: RouteInput with stops, vehicles, and distance matrix.

        Returns:
            RouteOutput with optimized route plans and metrics.
        """
        start_time = time.monotonic()

        # --- Build distance matrix (depots + stops) ---
        num_depots = problem.num_depots
        num_stops = problem.num_stops

        # Stops are indexed after depots in the matrix
        # depot 0..num_depots-1, then stops 0..num_stops-1
        full_matrix = problem.distance_matrix

        # --- Build OR-Tools model ---
        manager = pywrapcp.RoutingIndexManager(
            len(full_matrix),  # total nodes (depots + stops)
            problem.num_vehicles,
            problem.depot_indices,  # start nodes per vehicle
            problem.depot_indices,  # end nodes per vehicle (same as start)
        )

        routing = pywrapcp.RoutingModel(manager)

        # --- Distance callback ---
        def distance_callback(from_idx: int, to_idx: int) -> int:
            from_node = manager.IndexToNode(from_idx)
            to_node = manager.IndexToNode(to_idx)
            # Convert km to integer meters for OR-Tools (avoids float issues)
            return int(full_matrix[from_node][to_node] * 1000)

        distance_cb_idx = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(distance_cb_idx)

        # --- Time dimension ---
        def time_callback(from_idx: int, to_idx: int) -> int:
            """Return travel time in minutes between two nodes."""
            from_node = manager.IndexToNode(from_idx)
            to_node = manager.IndexToNode(to_idx)
            # Estimate: distance_km * (60 min / 30 km/h) = 2 min per km
            return int(full_matrix[from_node][to_node] * 2)

        time_cb_idx = routing.RegisterTransitCallback(time_callback)

        # Max time horizon: 24 hours = 1440 minutes
        horizon = 1440
        routing.AddDimension(
            time_cb_idx,
            horizon,  # max slack — allow waiting
            horizon,  # max cumulative time
            False,  # don't force start cumul to zero
            "Time",
        )
        time_dimension = routing.GetDimensionOrDie("Time")

        # --- Set time windows for stops ---
        for i, stop in enumerate(problem.stops):
            node_idx = num_depots + i
            routing_idx = manager.NodeToIndex(node_idx)
            if routing_idx < 0:
                continue

            tw_start = self._dt_to_min(stop.time_window_start)
            tw_end = self._dt_to_min(stop.time_window_end)

            time_dimension.CumulVar(routing_idx).SetRange(tw_start, tw_end)

        # --- Vehicle time windows ---
        for v_idx, vehicle in enumerate(problem.vehicles):
            start_min = self._dt_to_min(vehicle.work_start)
            end_min = self._dt_to_min(vehicle.work_end)
            idx = routing.Start(v_idx)
            time_dimension.CumulVar(idx).SetRange(start_min, end_min)
            idx = routing.End(v_idx)
            time_dimension.CumulVar(idx).SetRange(start_min, end_min)

        # --- Capacity dimension ---
        def demand_callback(from_idx: int) -> int:
            """Return demand change at node: +1 for pickup, -1 for delivery."""
            from_node = manager.IndexToNode(from_idx)
            if from_node < num_depots:
                return 0
            stop_idx = from_node - num_depots
            stop = problem.stops[stop_idx]
            return stop.demand if stop.is_pickup else -stop.demand

        demand_cb_idx = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimensionWithVehicleCapacity(
            demand_cb_idx,
            0,  # null capacity slack
            [v.capacity for v in problem.vehicles],  # vehicle capacities
            True,  # start cumul to zero
            "Capacity",
        )

        # --- Pickup-Delivery constraints ---
        # Each trip has exactly 1 pickup + 1 delivery.
        # Group stops by trip_id.
        trips: dict[int, list[tuple[int, RouteStop]]] = {}
        for i, stop in enumerate(problem.stops):
            trips.setdefault(stop.trip_id, []).append((i, stop))

        for trip_id, stops in trips.items():
            pickup_idx = None
            delivery_idx = None
            for si, stop in stops:
                if stop.is_pickup:
                    pickup_idx = num_depots + si
                elif stop.is_delivery:
                    delivery_idx = num_depots + si

            if pickup_idx is not None and delivery_idx is not None:
                pickup_routing = manager.NodeToIndex(pickup_idx)
                delivery_routing = manager.NodeToIndex(delivery_idx)
                if pickup_routing >= 0 and delivery_routing >= 0:
                    routing.AddPickupAndDelivery(pickup_routing, delivery_routing)
                    # Same vehicle for pickup and delivery
                    routing.solver().Add(
                        routing.VehicleVar(pickup_routing)
                        == routing.VehicleVar(delivery_routing)
                    )
                    # Pickup before delivery
                    routing.solver().Add(
                        time_dimension.CumulVar(pickup_routing)
                        <= time_dimension.CumulVar(delivery_routing)
                    )

        # --- Search strategy ---
        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
        )
        search_params.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_params.time_limit.FromSeconds(self.time_limit_sec)
        search_params.log_search = False

        # --- Solve ---
        solution = routing.SolveWithParameters(search_params)
        solve_time = time.monotonic() - start_time

        if not solution:
            return RouteOutput(
                routes=[],
                unassigned_trips=list(trips.keys()),
                total_distance_km=0.0,
                total_time_min=0.0,
                num_vehicles_used=0,
                solver_name="ortools",
                solve_time_sec=solve_time,
            )

        # --- Extract solution ---
        routes: list[RoutePlan] = []
        total_distance = 0.0
        total_time = 0

        for v_idx in range(problem.num_vehicles):
            route_stops: list[RouteStop] = []
            arrival_times: list[datetime] = []
            route_distance = 0
            route_time = 0

            idx = routing.Start(v_idx)
            while not routing.IsEnd(idx):
                node = manager.IndexToNode(idx)
                if node >= num_depots:
                    stop_idx = node - num_depots
                    route_stops.append(problem.stops[stop_idx])

                # Get arrival time
                cumul = solution.Min(time_dimension.CumulVar(idx))
                arrival_times.append(self._min_to_dt(cumul))

                next_idx = solution.Value(routing.NextVar(idx))
                route_distance += routing.GetArcCostForVehicle(idx, next_idx, v_idx)
                route_time += solution.Min(
                    time_dimension.CumulVar(next_idx)
                ) - solution.Min(time_dimension.CumulVar(idx))
                idx = next_idx

            if route_stops:
                route_km = route_distance / 1000.0  # convert back from meters
                routes.append(
                    RoutePlan(
                        vehicle_id=problem.vehicles[v_idx].vehicle_id,
                        stops=route_stops,
                        total_distance_km=route_km,
                        total_time_min=route_time,
                        arrival_times=arrival_times[1:],  # skip depot start time
                    )
                )
                total_distance += route_km
                total_time += route_time

        # Identify unassigned trips
        assigned_trips: set[int] = set()
        for route in routes:
            for stop in route.stops:
                assigned_trips.add(stop.trip_id)
        unassigned = [tid for tid in trips if tid not in assigned_trips]

        return RouteOutput(
            routes=routes,
            unassigned_trips=unassigned,
            total_distance_km=total_distance,
            total_time_min=total_time,
            num_vehicles_used=len(routes),
            solver_name="ortools",
            solve_time_sec=solve_time,
        )
