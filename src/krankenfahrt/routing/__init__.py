"""Routing module — PDVRPTW solver with OR-Tools and greedy baseline.

Provides:
- RouteInput / RouteOutput: Standardized data model for routing problems.
- OrtoolsPDVRPTWSolver: Google OR-Tools based PDVRPTW optimizer.
- GreedyPDVRPTWSolver: Fast heuristic baseline for comparison.
- DailyPipeline: Loads trips from DB, runs optimizer, assigns routes.
"""

from krankenfahrt.routing.models import RouteInput, RouteOutput, RouteStop, RoutePlan
from krankenfahrt.routing.ortools_solver import OrtoolsPDVRPTWSolver
from krankenfahrt.routing.greedy_solver import GreedyPDVRPTWSolver
from krankenfahrt.routing.pipeline import DailyPipeline

__all__ = [
    "RouteInput",
    "RouteOutput",
    "RouteStop",
    "RoutePlan",
    "OrtoolsPDVRPTWSolver",
    "GreedyPDVRPTWSolver",
    "DailyPipeline",
]
