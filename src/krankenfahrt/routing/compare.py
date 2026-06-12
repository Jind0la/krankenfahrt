"""Comparative analysis: OR-Tools vs Greedy Heuristic for PDVRPTW.

Runs both solvers on a set of test instances (scalable by trips, vehicles,
time window tightness) and produces tabular comparison output with metrics:
- Total distance
- Vehicles used
- Runtime
- Feasibility (assignments made)
- Cost savings

Usage:
    python -m krankenfahrt.routing.compare --trips 10 --vehicles 3 --runs 5
"""

import json
import math
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from krankenfahrt.routing.greedy_solver import GreedyPDVRPTWSolver
from krankenfahrt.routing.models import (
    RouteInput,
    RouteStop,
    VehicleSpec,
)
from krankenfahrt.routing.ortools_solver import OrtoolsPDVRPTWSolver


@dataclass
class InstanceConfig:
    """Configuration for a single test instance."""

    name: str
    num_trips: int
    num_vehicles: int
    capacity_per_vehicle: int = 2
    time_window_tightness: float = 0.5
    """0.0 = wide open, 1.0 = very tight windows."""
    seed: int = 42


@dataclass
class SolverResult:
    """Result of one solver on one instance."""

    solver_name: str
    instance_name: str
    total_distance_km: float = 0.0
    total_time_min: float = 0.0
    num_vehicles_used: int = 0
    num_trips_assigned: int = 0
    num_trips_total: int = 0
    solve_time_sec: float = 0.0
    feasible: bool = False

    @property
    def assignment_rate(self) -> float:
        if self.num_trips_total == 0:
            return 0.0
        return self.num_trips_assigned / self.num_trips_total

    @property
    def avg_distance_per_trip(self) -> float:
        if self.num_trips_assigned == 0:
            return 0.0
        return self.total_distance_km / self.num_trips_assigned


@dataclass
class ComparisonRow:
    """One row in the comparison table — two solvers on one instance."""

    instance: str
    trips: int
    vehicles: int
    ortools_dist: float
    ortools_time_sec: float
    ortools_assigned: int
    greedy_dist: float
    greedy_time_sec: float
    greedy_assigned: int
    dist_improvement_pct: float
    """Positive = OR-Tools is better."""


@dataclass
class ComparisonReport:
    """Complete comparison report."""

    rows: list[ComparisonRow] = field(default_factory=list)
    total_ortools_dist: float = 0.0
    total_greedy_dist: float = 0.0
    total_ortools_time: float = 0.0
    total_greedy_time: float = 0.0
    avg_improvement_pct: float = 0.0

    def add_row(self, row: ComparisonRow) -> None:
        self.rows.append(row)
        self.total_ortools_dist += row.ortools_dist
        self.total_greedy_dist += row.greedy_dist
        self.total_ortools_time += row.ortools_time_sec
        self.total_greedy_time += row.greedy_time_sec

    def finalize(self) -> None:
        if self.rows:
            self.avg_improvement_pct = sum(
                r.dist_improvement_pct for r in self.rows
            ) / len(self.rows)

    def format_table(self) -> str:
        """Format a readable ASCII table."""
        lines = []
        header = (
            f"{'Instance':<20} {'Trips':>5} {'Veh':>4} "
            f"{'OR-Tools':>10} {'OR-Time':>8} {'OR-OK':>6} "
            f"{'Greedy':>10} {'Gr-Time':>8} {'Gr-OK':>6} "
            f"{'Impr%':>7}"
        )
        sep = "=" * len(header)
        lines.append(sep)
        lines.append("PDVRPTW Solver Comparison: OR-Tools vs Greedy Heuristic")
        lines.append(sep)
        lines.append(header)
        lines.append("-" * len(header))

        for row in self.rows:
            lines.append(
                f"{row.instance:<20} {row.trips:>5} {row.vehicles:>4} "
                f"{row.ortools_dist:>10.1f} {row.ortools_time_sec:>7.2f}s {row.ortools_assigned:>5}/{row.trips} "
                f"{row.greedy_dist:>10.1f} {row.greedy_time_sec:>7.2f}s {row.greedy_assigned:>5}/{row.trips} "
                f"{row.dist_improvement_pct:>+6.1f}%"
            )

        lines.append("-" * len(header))
        lines.append(
            f"{'TOTAL / AVG':<20} {'':>5} {'':>4} "
            f"{self.total_ortools_dist:>10.1f} {self.total_ortools_time:>7.2f}s {'':>6} "
            f"{self.total_greedy_dist:>10.1f} {self.total_greedy_time:>7.2f}s {'':>6} "
            f"{self.avg_improvement_pct:>+6.1f}%"
        )
        lines.append(sep)

        improvement = self.avg_improvement_pct
        if improvement > 5:
            verdict = (
                f"VERDICT: OR-Tools significantly outperforms greedy "
                f"({abs(improvement):.1f}% less distance)"
            )
        elif improvement > 1:
            verdict = (
                f"VERDICT: OR-Tools moderately better than greedy "
                f"({abs(improvement):.1f}% distance savings)"
            )
        elif improvement > -5:
            verdict = "VERDICT: Comparable performance — greedy is a viable baseline"
        else:
            verdict = (
                f"VERDICT: Greedy outperforms OR-Tools! "
                f"({abs(improvement):.1f}% less distance — check OR-Tools config)"
            )
        lines.append(verdict)

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "rows": [
                {
                    "instance": r.instance,
                    "trips": r.trips,
                    "vehicles": r.vehicles,
                    "ortools_distance_km": r.ortools_dist,
                    "ortools_time_sec": r.ortools_time_sec,
                    "ortools_assigned": r.ortools_assigned,
                    "greedy_distance_km": r.greedy_dist,
                    "greedy_time_sec": r.greedy_time_sec,
                    "greedy_assigned": r.greedy_assigned,
                    "improvement_pct": r.dist_improvement_pct,
                }
                for r in self.rows
            ],
            "totals": {
                "ortools_total_distance_km": self.total_ortools_dist,
                "greedy_total_distance_km": self.total_greedy_dist,
                "ortools_total_time_sec": self.total_ortools_time,
                "greedy_total_time_sec": self.total_greedy_time,
                "avg_improvement_pct": self.avg_improvement_pct,
            },
        }


class ComparisonRunner:
    """Runs OR-Tools and Greedy solvers on a suite of test instances."""

    def __init__(
        self,
        ortools_time_limit: int = 30,
        base_date: date | None = None,
    ):
        self.ortools_time_limit = ortools_time_limit
        self.base_date = base_date or date(2024, 6, 15)

    def run_comparison(
        self,
        instances: list[InstanceConfig],
    ) -> ComparisonReport:
        """Run both solvers on all instances and produce comparison report.

        Args:
            instances: List of instance configurations to test.

        Returns:
            ComparisonReport with per-instance and aggregate metrics.
        """
        report = ComparisonReport()
        ortools_solver = OrtoolsPDVRPTWSolver(time_limit_sec=self.ortools_time_limit)
        greedy_solver = GreedyPDVRPTWSolver()

        for cfg in instances:
            # Build problem instance
            problem = self._build_instance(cfg)

            # Run OR-Tools
            ortools_result = ortools_solver.solve(problem)

            # Run Greedy
            greedy_result = greedy_solver.solve(problem)

            # Calculate improvement
            dist_improvement = 0.0
            if greedy_result.total_distance_km > 0:
                dist_improvement = (
                    (greedy_result.total_distance_km - ortools_result.total_distance_km)
                    / greedy_result.total_distance_km
                    * 100
                )

            ortools_assigned = problem.num_pickups - len(ortools_result.unassigned_trips)
            greedy_assigned = problem.num_pickups - len(greedy_result.unassigned_trips)

            row = ComparisonRow(
                instance=cfg.name,
                trips=cfg.num_trips,
                vehicles=cfg.num_vehicles,
                ortools_dist=ortools_result.total_distance_km,
                ortools_time_sec=ortools_result.solve_time_sec,
                ortools_assigned=ortools_assigned,
                greedy_dist=greedy_result.total_distance_km,
                greedy_time_sec=greedy_result.solve_time_sec,
                greedy_assigned=greedy_assigned,
                dist_improvement_pct=dist_improvement,
            )
            report.add_row(row)

        report.finalize()
        return report

    def _build_instance(self, cfg: InstanceConfig) -> RouteInput:
        """Build a RouteInput from an InstanceConfig."""
        rng = random.Random(cfg.seed)
        base_lat, base_lon = 52.5200, 13.4050  # Berlin

        # Generate random stop locations
        locations: list[tuple[float, float]] = []
        for _ in range(cfg.num_trips * 2):
            lat = base_lat + rng.uniform(-0.05, 0.05)
            lon = base_lon + rng.uniform(-0.05, 0.05)
            locations.append((lat, lon))

        # Build stops: each trip = 1 pickup + 1 delivery
        stops: list[RouteStop] = []
        for trip_id in range(1, cfg.num_trips + 1):
            pickup_loc = locations[(trip_id - 1) * 2]
            delivery_loc = locations[(trip_id - 1) * 2 + 1]

            # Pickup time window: staggered throughout the day
            hour = 7 + (trip_id % 9)
            minute = rng.randint(0, 59)
            pickup_time = datetime.combine(
                self.base_date,
                datetime.min.time().replace(hour=hour, minute=minute),
            )

            # Time window width: controlled by tightness
            # tightness=0 → 120 min window, tightness=1 → 10 min window
            tw_width = int(120 - cfg.time_window_tightness * 110)
            pickup_tw_start = pickup_time - timedelta(minutes=tw_width // 2)
            pickup_tw_end = pickup_time + timedelta(minutes=tw_width // 2)

            dropoff_time = pickup_time + timedelta(minutes=30 + rng.randint(0, 60))
            dropoff_tw_start = dropoff_time - timedelta(minutes=tw_width)
            dropoff_tw_end = dropoff_time + timedelta(minutes=tw_width)

            stops.append(
                RouteStop(
                    trip_id=trip_id,
                    lat=pickup_loc[0],
                    lon=pickup_loc[1],
                    stop_type="pickup",
                    time_window_start=pickup_tw_start,
                    time_window_end=pickup_tw_end,
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
                    time_window_start=dropoff_tw_start,
                    time_window_end=dropoff_tw_end,
                    service_duration_min=5,
                    demand=1,
                )
            )

        # Build vehicles
        vehicles: list[VehicleSpec] = []
        for v_id in range(1, cfg.num_vehicles + 1):
            vehicles.append(
                VehicleSpec(
                    vehicle_id=v_id,
                    capacity=cfg.capacity_per_vehicle,
                    depot_lat=base_lat,
                    depot_lon=base_lon,
                    work_start=datetime.combine(
                        self.base_date, datetime.min.time().replace(hour=7)
                    ),
                    work_end=datetime.combine(
                        self.base_date, datetime.min.time().replace(hour=16)
                    ),
                )
            )

        # Build distance matrix
        depot_coords = [(v.depot_lat, v.depot_lon) for v in vehicles]
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

        return RouteInput(
            stops=stops,
            vehicles=vehicles,
            distance_matrix=matrix,
            depot_indices=list(range(len(vehicles))),
        )

    @staticmethod
    def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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


# --- CLI Entry Point ---
def main():
    """Run comparison from command line."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Compare OR-Tools vs Greedy heuristic for PDVRPTW"
    )
    parser.add_argument("--trips", type=int, default=10, help="Base number of trips")
    parser.add_argument("--vehicles", type=int, default=3, help="Base number of vehicles")
    parser.add_argument("--runs", type=int, default=3, help="Number of instance configurations")
    parser.add_argument("--time-limit", type=int, default=30, help="OR-Tools time limit (seconds)")
    parser.add_argument("--json", type=str, default=None, help="Output JSON path")
    args = parser.parse_args()

    # Build test instances
    instances: list[InstanceConfig] = []
    for i in range(args.runs):
        scale = 1.0 + i * 0.5  # gradually increase difficulty
        instances.append(
            InstanceConfig(
                name=f"scale_{int(args.trips * scale)}t_{args.vehicles}v",
                num_trips=int(args.trips * scale),
                num_vehicles=args.vehicles,
                capacity_per_vehicle=2,
                time_window_tightness=min(0.9, 0.2 + i * 0.3),
                seed=42 + i,
            )
        )

    runner = ComparisonRunner(ortools_time_limit=args.time_limit)
    report = runner.run_comparison(instances)

    print(report.format_table())

    if args.json:
        with open(args.json, "w") as f:
            json.dump(report.to_dict(), f, indent=2, default=str)
        print(f"\nJSON report written to {args.json}")


if __name__ == "__main__":
    main()
