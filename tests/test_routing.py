"""Tests for the routing module.

Covers:
- RouteInput/RouteOutput data models
- OR-Tools PDVRPTW solver
- Greedy heuristic solver
- Daily pipeline (synthetic data path)
- Comparison framework
"""

import asyncio
import math
from datetime import date, datetime, timedelta

import pytest

from krankenfahrt.routing.models import (
    RouteInput,
    RouteOutput,
    RoutePlan,
    RouteStop,
    VehicleSpec,
)
from krankenfahrt.routing.ortools_solver import OrtoolsPDVRPTWSolver
from krankenfahrt.routing.greedy_solver import GreedyPDVRPTWSolver
from krankenfahrt.routing.pipeline import DailyPipeline, PipelineConfig
from krankenfahrt.routing.compare import (
    ComparisonReport,
    ComparisonRow,
    ComparisonRunner,
    InstanceConfig,
)


# ── Test fixtures ────────────────────────────────────────────────────────

def _make_base_date() -> datetime:
    return date(2024, 6, 15)


def _build_simple_problem(
    num_trips: int = 3,
    num_vehicles: int = 2,
    capacity: int = 2,
    seed: int = 42,
) -> RouteInput:
    """Build a simple test problem instance."""
    import random
    rng = random.Random(seed)

    base_lat, base_lon = 52.52, 13.40  # Berlin

    # Generate stops
    stops: list[RouteStop] = []
    for trip_id in range(1, num_trips + 1):
        p_lat = base_lat + rng.uniform(-0.03, 0.03)
        p_lon = base_lon + rng.uniform(-0.03, 0.03)
        d_lat = base_lat + rng.uniform(-0.03, 0.03)
        d_lon = base_lon + rng.uniform(-0.03, 0.03)

        hour = 7 + (trip_id % 9)
        pickup_time = datetime(2024, 6, 15, hour, rng.randint(0, 59))
        dropoff_time = pickup_time + timedelta(minutes=30 + rng.randint(0, 30))

        stops.append(
            RouteStop(
                trip_id=trip_id,
                lat=p_lat,
                lon=p_lon,
                stop_type="pickup",
                time_window_start=pickup_time - timedelta(minutes=30),
                time_window_end=pickup_time + timedelta(minutes=30),
                service_duration_min=5,
                demand=1,
            )
        )
        stops.append(
            RouteStop(
                trip_id=trip_id,
                lat=d_lat,
                lon=d_lon,
                stop_type="delivery",
                time_window_start=dropoff_time - timedelta(minutes=45),
                time_window_end=dropoff_time + timedelta(minutes=45),
                service_duration_min=5,
                demand=1,
            )
        )

    vehicles = [
        VehicleSpec(
            vehicle_id=i + 1,
            capacity=capacity,
            depot_lat=base_lat,
            depot_lon=base_lon,
            work_start=datetime(2024, 6, 15, 7, 0),
            work_end=datetime(2024, 6, 15, 16, 0),
        )
        for i in range(num_vehicles)
    ]

    # Build distance matrix: depots first, then stops
    depot_coords = [(v.depot_lat, v.depot_lon) for v in vehicles]
    stop_coords = [(s.lat, s.lon) for s in stops]
    all_coords = depot_coords + stop_coords

    matrix: list[list[float]] = []
    for i, (lat1, lon1) in enumerate(all_coords):
        row: list[float] = []
        for j, (lat2, lon2) in enumerate(all_coords):
            if i == j:
                row.append(0.0)
            else:
                row.append(_haversine_km(lat1, lon1, lat2, lon2))
        matrix.append(row)

    return RouteInput(
        stops=stops,
        vehicles=vehicles,
        distance_matrix=matrix,
        depot_indices=list(range(num_vehicles)),
    )


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
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


# ── Data model tests ──────────────────────────────────────────────────────


class TestRouteInput:
    def test_num_stops(self):
        problem = _build_simple_problem(num_trips=3)
        assert problem.num_stops == 6  # 3 trips × 2 stops
        assert problem.num_pickups == 3
        assert problem.num_deliveries == 3
        assert problem.num_vehicles == 2
        assert problem.num_depots == 2

    def test_distance_matrix_square(self):
        problem = _build_simple_problem(num_trips=5, num_vehicles=3)
        n = problem.num_vehicles + problem.num_stops
        assert len(problem.distance_matrix) == n
        for row in problem.distance_matrix:
            assert len(row) == n

    def test_distance_matrix_diagonal_zero(self):
        problem = _build_simple_problem(num_trips=2, num_vehicles=1)
        for i in range(len(problem.distance_matrix)):
            assert problem.distance_matrix[i][i] == 0.0


class TestRouteStop:
    def test_is_pickup(self):
        stop = RouteStop(
            trip_id=1,
            lat=52.5,
            lon=13.4,
            stop_type="pickup",
            time_window_start=datetime(2024, 6, 15, 8, 0),
            time_window_end=datetime(2024, 6, 15, 9, 0),
        )
        assert stop.is_pickup
        assert not stop.is_delivery

    def test_is_delivery(self):
        stop = RouteStop(
            trip_id=1,
            lat=52.5,
            lon=13.4,
            stop_type="delivery",
            time_window_start=datetime(2024, 6, 15, 9, 0),
            time_window_end=datetime(2024, 6, 15, 10, 0),
        )
        assert not stop.is_pickup
        assert stop.is_delivery


class TestRouteOutput:
    def test_summary_format(self):
        output = RouteOutput(
            routes=[],
            unassigned_trips=[],
            total_distance_km=42.5,
            total_time_min=180,
            num_vehicles_used=2,
            solver_name="test",
            solve_time_sec=1.5,
        )
        summary = output.summary()
        assert "42.5 km" in summary
        assert "180 min" in summary
        assert "test" in summary

    def test_feasible_when_all_assigned(self):
        output = RouteOutput(
            routes=[],
            unassigned_trips=[],
            total_distance_km=0,
            total_time_min=0,
            num_vehicles_used=0,
            solver_name="test",
        )
        assert output.is_feasible

    def test_not_feasible_with_unassigned(self):
        output = RouteOutput(
            routes=[],
            unassigned_trips=[1, 2],
            total_distance_km=0,
            total_time_min=0,
            num_vehicles_used=0,
            solver_name="test",
        )
        assert not output.is_feasible


# ── OR-Tools solver tests ─────────────────────────────────────────────────


class TestOrtoolsSolver:
    def test_solve_small_instance(self):
        problem = _build_simple_problem(num_trips=3, num_vehicles=2)
        solver = OrtoolsPDVRPTWSolver(time_limit_sec=10)
        result = solver.solve(problem)

        assert result.solver_name == "ortools"
        assert result.solve_time_sec > 0
        # Should assign all or most trips
        assigned = 0
        for route in result.routes:
            assigned += sum(1 for s in route.stops if s.is_pickup)
        assert assigned > 0, "No trips assigned"

    def test_solve_single_trip(self):
        problem = _build_simple_problem(num_trips=1, num_vehicles=1)
        solver = OrtoolsPDVRPTWSolver(time_limit_sec=10)
        result = solver.solve(problem)
        assert result.is_feasible
        assert len(result.routes) > 0

    def test_solve_many_trips(self):
        problem = _build_simple_problem(num_trips=5, num_vehicles=3)
        solver = OrtoolsPDVRPTWSolver(time_limit_sec=15)
        result = solver.solve(problem)
        # Should at least find a partial solution
        assert result.solve_time_sec > 0

    def test_pickup_before_delivery(self):
        """Verify that for each trip, pickup comes before delivery in the route."""
        problem = _build_simple_problem(num_trips=3, num_vehicles=2, seed=42)
        solver = OrtoolsPDVRPTWSolver(time_limit_sec=10)
        result = solver.solve(problem)

        for route in result.routes:
            seen_pickups: set[int] = set()
            for stop in route.stops:
                if stop.is_pickup:
                    seen_pickups.add(stop.trip_id)
                elif stop.is_delivery:
                    assert stop.trip_id in seen_pickups, (
                        f"Delivery for trip {stop.trip_id} before pickup"
                    )

    def test_return_empty_on_infeasible(self):
        """If time windows prevent any assignment, should return empty routes."""
        # Create stops with impossible time windows (all past midnight)
        stops = [
            RouteStop(
                trip_id=1,
                lat=52.52,
                lon=13.40,
                stop_type="pickup",
                time_window_start=datetime(2024, 6, 15, 2, 0),
                time_window_end=datetime(2024, 6, 15, 4, 0),
            ),
            RouteStop(
                trip_id=1,
                lat=52.53,
                lon=13.41,
                stop_type="delivery",
                time_window_start=datetime(2024, 6, 15, 3, 0),
                time_window_end=datetime(2024, 6, 15, 5, 0),
            ),
        ]
        vehicles = [
            VehicleSpec(
                vehicle_id=1,
                capacity=2,
                depot_lat=52.52,
                depot_lon=13.40,
                work_start=datetime(2024, 6, 15, 7, 0),
                work_end=datetime(2024, 6, 15, 16, 0),
            )
        ]
        matrix = [
            [0.0, 0.0, 1.0, 1.5],
            [0.0, 0.0, 1.0, 1.5],
            [1.0, 1.0, 0.0, 2.0],
            [1.5, 1.5, 2.0, 0.0],
        ]
        problem = RouteInput(
            stops=stops,
            vehicles=vehicles,
            distance_matrix=matrix,
            depot_indices=[0],
        )
        solver = OrtoolsPDVRPTWSolver(time_limit_sec=5)
        result = solver.solve(problem)
        # Trip times (2:00-5:00) are outside vehicle hours (7:00-16:00)
        assert not result.is_feasible


# ── Greedy solver tests ───────────────────────────────────────────────────


class TestGreedySolver:
    def test_solve_small_instance(self):
        problem = _build_simple_problem(num_trips=3, num_vehicles=2)
        solver = GreedyPDVRPTWSolver()
        result = solver.solve(problem)

        assert result.solver_name == "greedy"
        assert result.solve_time_sec >= 0
        assigned = 0
        for route in result.routes:
            assigned += sum(1 for s in route.stops if s.is_pickup)
        assert assigned > 0

    def test_solve_single_trip(self):
        problem = _build_simple_problem(num_trips=1, num_vehicles=1)
        solver = GreedyPDVRPTWSolver()
        result = solver.solve(problem)
        assert result.is_feasible
        assert len(result.routes) > 0

    def test_pickup_before_delivery(self):
        problem = _build_simple_problem(num_trips=3, num_vehicles=2, seed=42)
        solver = GreedyPDVRPTWSolver()
        result = solver.solve(problem)

        for route in result.routes:
            seen_pickups: set[int] = set()
            for stop in route.stops:
                if stop.is_pickup:
                    seen_pickups.add(stop.trip_id)
                elif stop.is_delivery:
                    assert stop.trip_id in seen_pickups, (
                        f"Delivery before pickup for trip {stop.trip_id}"
                    )

    def test_capacity_not_exceeded(self):
        problem = _build_simple_problem(num_trips=5, num_vehicles=2, capacity=2)
        solver = GreedyPDVRPTWSolver()
        result = solver.solve(problem)

        for route in result.routes:
            load = 0
            for stop in route.stops:
                load += stop.demand if stop.is_pickup else -stop.demand
                assert load <= 2, f"Capacity exceeded: {load} > 2"

    def test_deterministic(self):
        problem = _build_simple_problem(num_trips=3, num_vehicles=2, seed=42)
        solver = GreedyPDVRPTWSolver()
        result1 = solver.solve(problem)
        result2 = solver.solve(problem)
        assert result1.total_distance_km == result2.total_distance_km

    def test_all_trips_assigned_for_small_instance(self):
        problem = _build_simple_problem(num_trips=3, num_vehicles=3)
        solver = GreedyPDVRPTWSolver()
        result = solver.solve(problem)
        assigned = sum(
            1 for r in result.routes for s in r.stops if s.is_pickup
        )
        assert assigned == 3, f"Expected 3, got {assigned}"


# ── Pipeline tests ────────────────────────────────────────────────────────


class TestDailyPipeline:
    def test_synthetic_data_generation(self):
        """Pipeline should generate synthetic data when DB not available."""
        config = PipelineConfig(
            target_date=date(2024, 6, 15),
            mode="greedy",
        )
        pipeline = DailyPipeline(config)
        result = asyncio.run(pipeline.run())

        assert result.success, f"Pipeline failed: {result.error}"
        assert result.trips_loaded > 0
        assert result.vehicles_loaded > 0
        assert result.output is not None
        assert len(result.output.routes) > 0

    def test_ortools_mode(self):
        config = PipelineConfig(
            target_date=date(2024, 6, 15),
            mode="ortools",
            ortools_time_limit_sec=10,
        )
        pipeline = DailyPipeline(config)
        result = asyncio.run(pipeline.run())
        assert result.success
        assert result.output.solver_name == "ortools"

    def test_deterministic_synthetic_data(self):
        """Same date should produce same synthetic data."""
        config = PipelineConfig(target_date=date(2024, 6, 15), mode="greedy")
        p1 = DailyPipeline(config)
        p2 = DailyPipeline(config)
        r1 = asyncio.run(p1.run())
        r2 = asyncio.run(p2.run())
        assert r1.trips_loaded == r2.trips_loaded
        assert len(r1.output.routes) == len(r2.output.routes)

    def test_empty_date(self):
        """Pipeline should handle date with no trips (DB fallback)."""
        config = PipelineConfig(
            target_date=date(2024, 6, 15),
            mode="greedy",
            output_json_path="/tmp/krankenfahrt_test_output.json",
        )
        pipeline = DailyPipeline(config)
        result = asyncio.run(pipeline.run())
        assert result.success
        # Should have written JSON output
        import os
        assert os.path.exists("/tmp/krankenfahrt_test_output.json")
        os.unlink("/tmp/krankenfahrt_test_output.json")


# ── Comparison tests ──────────────────────────────────────────────────────


class TestComparisonReport:
    def test_empty_report(self):
        report = ComparisonReport()
        report.finalize()
        assert report.avg_improvement_pct == 0.0
        assert len(report.rows) == 0

    def test_single_row(self):
        report = ComparisonReport()
        report.add_row(ComparisonRow(
            instance="test",
            trips=5,
            vehicles=2,
            ortools_dist=100.0,
            ortools_time_sec=5.0,
            ortools_assigned=5,
            greedy_dist=120.0,
            greedy_time_sec=0.1,
            greedy_assigned=5,
            dist_improvement_pct=16.67,
        ))
        report.finalize()
        assert report.avg_improvement_pct == 16.67

    def test_format_table(self):
        report = ComparisonReport()
        report.add_row(ComparisonRow(
            instance="test_inst",
            trips=3,
            vehicles=2,
            ortools_dist=22.5,
            ortools_time_sec=10.0,
            ortools_assigned=3,
            greedy_dist=25.0,
            greedy_time_sec=0.01,
            greedy_assigned=3,
            dist_improvement_pct=10.0,
        ))
        report.finalize()
        table = report.format_table()
        assert "test_inst" in table
        assert "22.5" in table
        assert "25.0" in table
        assert "+10.0%" in table

    def test_to_dict(self):
        report = ComparisonReport()
        report.add_row(ComparisonRow(
            instance="inst",
            trips=3,
            vehicles=1,
            ortools_dist=10.0,
            ortools_time_sec=1.0,
            ortools_assigned=3,
            greedy_dist=12.0,
            greedy_time_sec=0.01,
            greedy_assigned=3,
            dist_improvement_pct=16.7,
        ))
        report.finalize()
        d = report.to_dict()
        assert len(d["rows"]) == 1
        assert d["rows"][0]["ortools_distance_km"] == 10.0
        assert "totals" in d


class TestComparisonRunner:
    def test_run_single_instance(self):
        runner = ComparisonRunner(ortools_time_limit=10)
        instances = [
            InstanceConfig(
                name="test_3t",
                num_trips=3,
                num_vehicles=2,
                capacity_per_vehicle=2,
                time_window_tightness=0.3,
                seed=42,
            )
        ]
        report = runner.run_comparison(instances)
        assert len(report.rows) == 1
        row = report.rows[0]
        assert row.trips == 3
        assert row.ortools_time_sec > 0
        assert row.greedy_time_sec >= 0

    def test_run_multiple_instances(self):
        runner = ComparisonRunner(ortools_time_limit=15)
        instances = [
            InstanceConfig(name=f"test_{n}t", num_trips=n, num_vehicles=2, seed=42)
            for n in [2, 3, 4]
        ]
        report = runner.run_comparison(instances)
        assert len(report.rows) == 3


# ── Cross-solver consistency tests ────────────────────────────────────────


class TestCrossSolverConsistency:
    """Verify that both solvers produce consistent output formats."""

    def test_both_assign_all_trips_for_easy_instance(self):
        """For an easy instance (few trips, many vehicles), both should assign all."""
        problem = _build_simple_problem(num_trips=3, num_vehicles=3, capacity=2, seed=42)

        ortools = OrtoolsPDVRPTWSolver(time_limit_sec=10)
        greedy = GreedyPDVRPTWSolver()

        o_result = ortools.solve(problem)
        g_result = greedy.solve(problem)

        o_assigned = sum(1 for r in o_result.routes for s in r.stops if s.is_pickup)
        g_assigned = sum(1 for r in g_result.routes for s in r.stops if s.is_pickup)

        assert o_assigned == 3, f"OR-Tools assigned {o_assigned}/3"
        assert g_assigned == 3, f"Greedy assigned {g_assigned}/3"

    def test_output_format_compatibility(self):
        """Both outputs should have same structure (routes, stops, arrival times)."""
        problem = _build_simple_problem(num_trips=3, num_vehicles=2, seed=42)
        ortools = OrtoolsPDVRPTWSolver(time_limit_sec=10)
        greedy = GreedyPDVRPTWSolver()

        for solver, result in [("ortools", ortools.solve(problem)), ("greedy", greedy.solve(problem))]:
            assert isinstance(result, RouteOutput), f"{solver}: wrong type"
            assert isinstance(result.total_distance_km, float), f"{solver}: distance not float"
            for route in result.routes:
                assert isinstance(route, RoutePlan), f"{solver}: route not RoutePlan"
                assert route.total_distance_km >= 0, f"{solver}: negative distance"
                for stop in route.stops:
                    assert isinstance(stop, RouteStop), f"{solver}: stop not RouteStop"

    def test_ortools_better_or_equal_on_small(self):
        """On small instances, OR-Tools should find distance <= greedy distance."""
        problem = _build_simple_problem(num_trips=3, num_vehicles=2, seed=42)
        ortools = OrtoolsPDVRPTWSolver(time_limit_sec=10)
        greedy = GreedyPDVRPTWSolver()

        o = ortools.solve(problem)
        g = greedy.solve(problem)

        # OR-Tools should not be worse (allowing small tolerance for randomness)
        assert o.total_distance_km <= g.total_distance_km + 1.0, (
            f"OR-Tools ({o.total_distance_km:.1f}) worse than greedy ({g.total_distance_km:.1f})"
        )
