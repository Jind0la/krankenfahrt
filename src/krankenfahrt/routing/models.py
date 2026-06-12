"""Data models for routing problems.

Standardized I/O format shared by OR-Tools solver and greedy heuristic.
This enables direct comparison between optimization approaches.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RouteStop:
    """A single stop in a route — pickup or delivery for one trip."""

    trip_id: int
    """Database ID of the trip this stop belongs to."""

    lat: float
    lon: float
    """GPS coordinates of this stop."""

    stop_type: str  # "pickup" | "delivery"
    """Whether this is the pickup or delivery for the trip."""

    time_window_start: datetime
    time_window_end: datetime
    """Time window during which this stop must be served."""

    service_duration_min: int = 5
    """Minutes needed at this stop (loading/unloading patient)."""

    demand: int = 1
    """Vehicle capacity units consumed (1 patient = 1 unit)."""

    node_index: int = -1
    """Set by solver: index in the distance matrix."""

    @property
    def is_pickup(self) -> bool:
        return self.stop_type == "pickup"

    @property
    def is_delivery(self) -> bool:
        return self.stop_type == "delivery"


@dataclass
class VehicleSpec:
    """A vehicle available for routing."""

    vehicle_id: int
    """Database ID of the vehicle."""

    capacity: int = 1
    """How many patients can be transported simultaneously."""

    depot_lat: float = 0.0
    depot_lon: float = 0.0
    """Starting/ending location for this vehicle."""

    work_start: datetime = field(default_factory=lambda: datetime(2024, 1, 1, 7, 0))
    work_end: datetime = field(default_factory=lambda: datetime(2024, 1, 1, 16, 0))
    """Working hours for this vehicle."""

    cost_per_km: float = 1.0
    """Operating cost per kilometer travelled."""


@dataclass
class RouteInput:
    """Complete routing problem instance.

    Contains all stops (pickup + delivery pairs), available vehicles,
    and a distance matrix for efficient lookups.
    """

    stops: list[RouteStop]
    vehicles: list[VehicleSpec]
    distance_matrix: list[list[float]]
    """Square matrix: distance_matrix[i][j] = distance in km from stop i to stop j."""

    depot_indices: list[int]
    """Indices of depot nodes in the distance matrix. Depots are prepended to the
    distance matrix before stops: depot_indices = [0, 1, ...]."""

    @property
    def num_stops(self) -> int:
        return len(self.stops)

    @property
    def num_vehicles(self) -> int:
        return len(self.vehicles)

    @property
    def num_pickups(self) -> int:
        return sum(1 for s in self.stops if s.is_pickup)

    @property
    def num_deliveries(self) -> int:
        return sum(1 for s in self.stops if s.is_delivery)

    @property
    def num_depots(self) -> int:
        return len(self.depot_indices)


@dataclass
class RoutePlan:
    """A single vehicle's route plan."""

    vehicle_id: int
    """Which vehicle this route is for."""

    stops: list[RouteStop]
    """Ordered list of stops for this vehicle."""

    total_distance_km: float = 0.0
    """Total distance travelled on this route."""

    total_time_min: float = 0.0
    """Total route duration including service times."""

    arrival_times: list[datetime] = field(default_factory=list)
    """Scheduled arrival time at each stop."""


@dataclass
class RouteOutput:
    """Complete solution to a routing problem.

    Contains route plans for each vehicle plus summary metrics.
    Compatible with both OR-Tools and greedy solver outputs.
    """

    routes: list[RoutePlan]
    """One route plan per used vehicle."""

    unassigned_trips: list[int] = field(default_factory=list)
    """Trip IDs that could not be assigned to any vehicle."""

    total_distance_km: float = 0.0
    total_time_min: float = 0.0
    num_vehicles_used: int = 0

    solver_name: str = "unknown"
    solve_time_sec: float = 0.0

    @property
    def is_feasible(self) -> bool:
        """True if all trips were assigned."""
        return len(self.unassigned_trips) == 0

    def summary(self) -> str:
        return (
            f"[{self.solver_name}] {len(self.routes)} routes, "
            f"{self.total_distance_km:.1f} km, {self.total_time_min:.0f} min, "
            f"{len(self.unassigned_trips)} unassigned"
        )
