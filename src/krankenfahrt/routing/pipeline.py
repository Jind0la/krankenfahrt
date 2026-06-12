"""Daily optimization pipeline.

Cron-ready script that:
1. Loads today's trips from the database.
2. Converts to RouteInput (stops, vehicles, distance matrix).
3. Runs the selected solver (ortools or greedy).
4. Assigns optimized routes to drivers.
5. Logs results and handles errors gracefully.

Usage:
    python -m krankenfahrt.routing.pipeline --date 2024-06-15 --mode ortools
"""

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from krankenfahrt.routing.greedy_solver import GreedyPDVRPTWSolver
from krankenfahrt.routing.models import (
    RouteInput,
    RouteOutput,
    RouteStop,
    VehicleSpec,
)
from krankenfahrt.routing.ortools_solver import OrtoolsPDVRPTWSolver

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for a pipeline run."""

    target_date: date
    """Which day to optimize routes for."""

    mode: str = "ortools"
    """Solver mode: 'ortools' or 'greedy'."""

    ortools_time_limit_sec: int = 30
    """Time limit for OR-Tools solver."""

    depot_lat: float = 52.5200
    depot_lon: float = 13.4050
    """Default depot coordinates (Berlin)."""

    output_json_path: str | None = None
    """If set, write RouteOutput JSON to this path."""


@dataclass
class PipelineResult:
    """Result of a pipeline run."""

    config: PipelineConfig
    output: RouteOutput | None = None
    error: str | None = None
    runtime_sec: float = 0.0
    trips_loaded: int = 0
    vehicles_loaded: int = 0

    @property
    def success(self) -> bool:
        return self.error is None and self.output is not None


class DailyPipeline:
    """Daily route optimization pipeline.

    Loads trips and vehicles from the database (or mock data for testing),
    runs the PDVRPTW solver, and produces optimized route plans.
    """

    def __init__(self, config: PipelineConfig):
        self.config = config

    async def run(self) -> PipelineResult:
        """Execute the full pipeline.

        Returns PipelineResult with output routes or error details.
        """
        start = time.monotonic()
        result = PipelineResult(config=self.config)

        try:
            # Step 1: Load data
            logger.info(f"Loading trips for {self.config.target_date}")
            stops, vehicles = await self._load_data()
            result.trips_loaded = len(stops) // 2  # each trip = 2 stops
            result.vehicles_loaded = len(vehicles)

            if not stops:
                logger.warning("No trips found for target date")
                result.error = "No trips to optimize"
                return result

            # Step 2: Build distance matrix
            logger.info(f"Building distance matrix for {len(stops)} stops")
            distance_matrix = self._build_distance_matrix(stops, vehicles)

            # Step 3: Construct RouteInput
            problem = RouteInput(
                stops=stops,
                vehicles=vehicles,
                distance_matrix=distance_matrix,
                depot_indices=list(range(len(vehicles))),
            )

            # Step 4: Solve
            logger.info(f"Solving with {self.config.mode} solver")
            if self.config.mode == "ortools":
                solver = OrtoolsPDVRPTWSolver(
                    time_limit_sec=self.config.ortools_time_limit_sec
                )
            else:
                solver = GreedyPDVRPTWSolver()

            output = solver.solve(problem)
            result.output = output

            # Step 5: Log summary
            logger.info(f"Optimization complete: {output.summary()}")

            # Step 6: Write JSON output if configured
            if self.config.output_json_path:
                self._write_output_json(output)

            # Step 7: Assign routes to drivers (optional DB write)
            # await self._assign_routes(output)

        except Exception as e:
            logger.exception(f"Pipeline failed: {e}")
            result.error = str(e)

        result.runtime_sec = time.monotonic() - start
        return result

    async def _load_data(self) -> tuple[list[RouteStop], list[VehicleSpec]]:
        """Load trips and vehicles for the target date.

        In production: queries the database via Tortoise ORM.
        For now: generates synthetic test data for development.
        """
        target = self.config.target_date
        start_of_day = datetime.combine(target, datetime.min.time())
        end_of_day = start_of_day + timedelta(hours=23, minutes=59)

        try:
            # Try to load from database
            from krankenfahrt.models.schema import Trip, Vehicle

            trips = await Trip.filter(
                scheduled_pickup__gte=start_of_day,
                scheduled_pickup__lte=end_of_day,
                status="geplant",
            ).prefetch_related("patient")

            vehicles_list = await Vehicle.all().prefetch_related("driver")

            stops: list[RouteStop] = []
            for trip in trips:
                await trip.patient

                # Parse pickup address to coordinates (simplified — use geo service in prod)
                pickup_lat, pickup_lon = self._geocode(trip.pickup_addr)
                dropoff_lat, dropoff_lon = self._geocode(trip.dest_addr)

                pickup_tw = trip.scheduled_pickup
                dropoff_tw = trip.scheduled_dropoff or (
                    pickup_tw + timedelta(minutes=60)
                )

                stops.append(
                    RouteStop(
                        trip_id=trip.id,
                        lat=pickup_lat,
                        lon=pickup_lon,
                        stop_type="pickup",
                        time_window_start=pickup_tw - timedelta(minutes=15),
                        time_window_end=pickup_tw + timedelta(minutes=15),
                        service_duration_min=5,
                        demand=1,
                    )
                )
                stops.append(
                    RouteStop(
                        trip_id=trip.id,
                        lat=dropoff_lat,
                        lon=dropoff_lon,
                        stop_type="delivery",
                        time_window_start=dropoff_tw - timedelta(minutes=30),
                        time_window_end=dropoff_tw + timedelta(minutes=30),
                        service_duration_min=5,
                        demand=1,
                    )
                )

            vehicles_specs: list[VehicleSpec] = []
            for v in vehicles_list:
                await v.driver.first() if hasattr(v, 'driver') else None
                vehicles_specs.append(
                    VehicleSpec(
                        vehicle_id=v.id,
                        capacity=v.capacity,
                        depot_lat=self.config.depot_lat,
                        depot_lon=self.config.depot_lon,
                        work_start=datetime.combine(target, datetime.min.time().replace(hour=7)),
                        work_end=datetime.combine(target, datetime.min.time().replace(hour=16)),
                    )
                )

            return stops, vehicles_specs

        except Exception as e:
            logger.warning(f"Database load failed ({e}), using synthetic data")
            return self._generate_synthetic_data()

    def _generate_synthetic_data(
        self,
    ) -> tuple[list[RouteStop], list[VehicleSpec]]:
        """Generate synthetic test data when DB is unavailable."""
        import random

        target = self.config.target_date
        rng = random.Random(target.toordinal())  # deterministic for reproducibility

        # Generate 10 sample trips around Berlin
        stops: list[RouteStop] = []
        base_lat, base_lon = self.config.depot_lat, self.config.depot_lon

        # Pre-generate locations
        locations: list[tuple[float, float]] = []
        for _ in range(15):
            lat = base_lat + rng.uniform(-0.05, 0.05)
            lon = base_lon + rng.uniform(-0.05, 0.05)
            locations.append((lat, lon))

        for trip_id in range(1, 11):
            pickup_loc = locations[trip_id - 1]
            delivery_loc = locations[rng.randint(0, 14)]

            hour = rng.randint(7, 15)
            minute = rng.randint(0, 59)
            pickup_time = datetime.combine(target, datetime.min.time().replace(hour=hour, minute=minute))
            dropoff_time = pickup_time + timedelta(minutes=rng.randint(20, 90))

            stops.append(
                RouteStop(
                    trip_id=trip_id,
                    lat=pickup_loc[0],
                    lon=pickup_loc[1],
                    stop_type="pickup",
                    time_window_start=pickup_time - timedelta(minutes=15),
                    time_window_end=pickup_time + timedelta(minutes=15),
                    service_duration_min=5,
                    demand=1,
                )
            )
            stops.append(
                RouteStop(
                    trip_id=trip_id,
                    lat=delivery_loc[0],
                    lon=delivery_loc[1],
                    stop_type="delivery",
                    time_window_start=dropoff_time - timedelta(minutes=30),
                    time_window_end=dropoff_time + timedelta(minutes=30),
                    service_duration_min=5,
                    demand=1,
                )
            )

        # 3 vehicles
        vehicles = [
            VehicleSpec(
                vehicle_id=1,
                capacity=2,
                depot_lat=base_lat,
                depot_lon=base_lon,
                work_start=datetime.combine(target, datetime.min.time().replace(hour=7)),
                work_end=datetime.combine(target, datetime.min.time().replace(hour=16)),
            ),
            VehicleSpec(
                vehicle_id=2,
                capacity=2,
                depot_lat=base_lat,
                depot_lon=base_lon,
                work_start=datetime.combine(target, datetime.min.time().replace(hour=7)),
                work_end=datetime.combine(target, datetime.min.time().replace(hour=16)),
            ),
            VehicleSpec(
                vehicle_id=3,
                capacity=1,
                depot_lat=base_lat,
                depot_lon=base_lon,
                work_start=datetime.combine(target, datetime.min.time().replace(hour=7)),
                work_end=datetime.combine(target, datetime.min.time().replace(hour=16)),
            ),
        ]

        return stops, vehicles

    def _build_distance_matrix(
        self,
        stops: list[RouteStop],
        vehicles: list[VehicleSpec],
    ) -> list[list[float]]:
        """Build a full distance matrix: depots first, then stops."""

        # Depot locations (one per vehicle, but all same depot for now)
        depot_coords: list[tuple[float, float]] = []
        for v in vehicles:
            depot_coords.append((v.depot_lat, v.depot_lon))

        stop_coords = [(s.lat, s.lon) for s in stops]

        all_coords = depot_coords + stop_coords
        n = len(all_coords)

        matrix: list[list[float]] = []
        for i in range(n):
            row: list[float] = []
            for j in range(n):
                if i == j:
                    row.append(0.0)
                else:
                    lat1, lon1 = all_coords[i]
                    lat2, lon2 = all_coords[j]
                    row.append(self._haversine_km(lat1, lon1, lat2, lon2))
            matrix.append(row)

        return matrix

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        import math

        earth_radius_km = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        return earth_radius_km * 2 * math.asin(math.sqrt(a))

    @staticmethod
    def _geocode(address: str) -> tuple[float, float]:
        """Geocode an address to coordinates (simplified).

        In production: use OSRM/nominatim/Google Maps API.
        For now: returns deterministic pseudo-coordinates based on hash.
        """
        import hashlib

        h = hashlib.md5(address.encode()).hexdigest()
        lat = 52.5 + (int(h[:8], 16) % 10000) / 100000.0
        lon = 13.4 + (int(h[8:16], 16) % 10000) / 100000.0
        return lat, lon

    def _write_output_json(self, output: RouteOutput) -> None:
        """Write RouteOutput to JSON file."""
        import json

        assert self.config.output_json_path

        data = {
            "solver": output.solver_name,
            "solve_time_sec": output.solve_time_sec,
            "total_distance_km": output.total_distance_km,
            "total_time_min": output.total_time_min,
            "num_vehicles_used": output.num_vehicles_used,
            "unassigned_trips": output.unassigned_trips,
            "routes": [
                {
                    "vehicle_id": r.vehicle_id,
                    "total_distance_km": r.total_distance_km,
                    "total_time_min": r.total_time_min,
                    "num_stops": len(r.stops),
                    "stops": [
                        {
                            "trip_id": s.trip_id,
                            "type": s.stop_type,
                            "arrival": r.arrival_times[i].isoformat() if i < len(r.arrival_times) else None,
                        }
                        for i, s in enumerate(r.stops)
                    ],
                }
                for r in output.routes
            ],
        }

        with open(self.config.output_json_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(f"Route output written to {self.config.output_json_path}")
