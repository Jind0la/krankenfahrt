"""Auto-assignment handler — triggers on new trip creation.

When a new trip (status='geplant') is created, this handler:
1. Queries all active, available drivers
2. Calls the existing dispatch engine to find the best match
3. If matched: assigns driver, transitions to 'zugewiesen', notifies driver
4. If no match: escalates to human dispatcher (chef)

The existing manual assignment flow is unchanged — this only fires on
freshly-created 'geplant' trips that have no driver yet.

Dependencies are injected via constructor so tests can swap in mocks/spies.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog

from krankenfahrt.core.dispatch import GreedyDispatchEngine
from krankenfahrt.core.notification import Messages
from krankenfahrt.models.schema import Driver, Trip

logger = structlog.get_logger(__name__)


# ── Result type ────────────────────────────────────────────────────────────


@dataclass
class AutoDispatchResult:
    """Outcome of an auto-assignment attempt.

    Attributes
    ----------
    matched : bool
        True if a driver was found and assigned.
    assigned_driver_id : int or None
        Database ID of the assigned driver (None if no match).
    escalation_reason : str or None
        Human-readable reason for escalation (None if matched).
    """

    matched: bool
    assigned_driver_id: int | None = None
    escalation_reason: str | None = None


# ── Notification interface (duck-typed; no ABC so tests can use simple spies) ─


class NotificationSender:
    """Protocol for sending notifications to drivers and dispatchers.

    Implementations handle the actual delivery (Telegram, push, SMS, etc.).
    Tests provide a spy that records calls for assertion.
    """

    async def send_to_driver(self, driver_id: int, message: str) -> None:
        """Send a message to a specific driver (by telegram_id or internal id)."""
        raise NotImplementedError

    async def send_to_chef(self, message: str) -> None:
        """Send an escalation message to the dispatcher / chef."""
        raise NotImplementedError


# ── Driver query callback ──────────────────────────────────────────────────

# Type alias for a callable that returns all active, available drivers.
# In production this queries Tortoise ORM; in tests it returns a fixed list.
DriverQueryFn = Callable[[], Awaitable[list[Driver]]]


# ── Handler ────────────────────────────────────────────────────────────────


class AutoDispatchHandler:
    """Handles automatic driver assignment for newly created trips.

    Dependencies are injected so the handler doesn't couple to the database
    or messaging layer directly.

    Parameters
    ----------
    engine : GreedyDispatchEngine
        The dispatch engine that finds the best driver for a trip.
    notifier : NotificationSender
        Object with ``send_to_driver(driver_id, message)`` and
        ``send_to_chef(message)`` async methods.
    get_available_drivers : callable
        Async callable that returns ``list[Driver]`` of all drivers who are
        currently active and not on break.
    """

    def __init__(
        self,
        engine: GreedyDispatchEngine,
        notifier: NotificationSender,
        get_available_drivers: DriverQueryFn,
    ):
        self._engine = engine
        self._notifier = notifier
        self._get_available_drivers = get_available_drivers

    async def handle_new_trip(self, trip: Trip) -> AutoDispatchResult:
        """Run auto-assignment for a single newly created trip.

        If the trip already has a driver assigned (e.g., manual assignment
        happened first), this is a no-op and returns ``matched=True`` with
        the existing driver id.

        Parameters
        ----------
        trip : Trip
            The trip to assign. Expected to be in 'geplant' state.

        Returns
        -------
        AutoDispatchResult
        """
        # ── Guard: already assigned ────────────────────────────────────
        if trip.driver is not None:
            logger.info(
                "trip_already_assigned",
                trip_id=trip.id,
                driver_id=trip.driver.id,
                status=trip.status,
            )
            return AutoDispatchResult(
                matched=True,
                assigned_driver_id=trip.driver.id,
            )

        # ── Fetch available drivers ────────────────────────────────────
        available = await self._get_available_drivers()
        logger.debug(
            "auto_dispatch_fetch_drivers",
            trip_id=trip.id,
            available_count=len(available),
        )

        if not available:
            reason = "Kein aktiver Fahrer verfügbar"
            logger.warning("auto_dispatch_no_drivers", trip_id=trip.id)
            await self._escalate(trip, reason)
            return AutoDispatchResult(matched=False, escalation_reason=reason)

        # ── Run matching engine ────────────────────────────────────────
        assignment = await self._engine.find_best_driver(trip, available)

        if assignment is None:
            reason = "Kein passender Fahrer gefunden (Qualifikation, Fahrzeugtyp, Verfügbarkeit)"
            logger.warning(
                "auto_dispatch_no_match",
                trip_id=trip.id,
                drivers_checked=len(available),
            )
            await self._escalate(trip, reason)
            return AutoDispatchResult(matched=False, escalation_reason=reason)

        # ── Assign driver ──────────────────────────────────────────────
        driver = assignment.driver
        trip.driver = driver
        trip.vehicle = driver.vehicle
        trip.status = "zugewiesen"

        # Persist if the trip has a real ORM .save()
        if hasattr(trip, "save"):
            await trip.save()

        logger.info(
            "auto_dispatch_assigned",
            trip_id=trip.id,
            driver_id=driver.id,
            driver_name=driver.name,
            distance_km=assignment.distance_km,
            score=assignment.score,
        )

        # ── Notify driver ──────────────────────────────────────────────
        await self._notify_driver(driver, trip)

        return AutoDispatchResult(
            matched=True,
            assigned_driver_id=driver.id,
        )

    # ── Private helpers ────────────────────────────────────────────────────

    async def _notify_driver(self, driver: Driver, trip: Trip) -> None:
        """Send the 'new trip' notification to the assigned driver."""
        patient = await trip.patient if hasattr(trip, "patient") and callable(getattr(trip, "patient", None)) else trip.patient  # type: ignore[union-attr]  # noqa: E501

        patient_name = getattr(patient, "name", "Unbekannt")
        pickup_time = Messages.format_time(trip.scheduled_pickup)
        pickup_addr = trip.pickup_addr
        dest_addr = trip.dest_addr
        vehicle_type = getattr(patient, "vehicle_type", "Sitz")
        special_needs = getattr(patient, "special_needs", None)

        message = Messages.DRIVER_NEW_TRIP.format(
            patient_name=patient_name,
            pickup_time=pickup_time,
            pickup_addr=pickup_addr,
            dest_addr=dest_addr,
            vehicle_type=vehicle_type,
            special_needs=f"📝 {special_needs}" if special_needs else "",
            nav_link=f"https://maps.google.com/?q={pickup_addr.replace(' ', '+')}",
        )

        driver_telegram_id = getattr(driver, "telegram_id", driver.id)
        await self._notifier.send_to_driver(driver_telegram_id, message)

        logger.info(
            "auto_dispatch_notified_driver",
            trip_id=trip.id,
            driver_id=driver.id,
        )

    async def _escalate(self, trip: Trip, reason: str) -> None:
        """Escalate an unassigned trip to the human dispatcher (chef)."""
        patient = trip.patient
        patient_name = getattr(patient, "name", "Unbekannt")

        message = (
            f"⚠️ **Eskalation: Kein Fahrer zugewiesen!**\n\n"
            f"Fahrt #{trip.id}: {patient_name}\n"
            f"Abholung: {Messages.format_time(trip.scheduled_pickup)}\n"
            f"Von: {trip.pickup_addr}\n"
            f"Nach: {trip.dest_addr}\n"
            f"Grund: {reason}\n\n"
            f"Bitte manuell einen Fahrer zuweisen."
        )

        await self._notifier.send_to_chef(message)

        logger.info(
            "auto_dispatch_escalated",
            trip_id=trip.id,
            reason=reason,
        )
