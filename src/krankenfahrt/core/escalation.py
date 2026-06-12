"""Escalation management service — triggers, options, audit log.

Provides:
- Escalation creation (manual and automatic timeout-based)
- Option processing (reassign, pause, cancel, acknowledge, resolve)
- Audit log querying for compliance and troubleshooting
"""

from datetime import UTC, datetime, timedelta

import structlog

from krankenfahrt.config import config
from krankenfahrt.models.schema import Escalation, Trip

logger = structlog.get_logger(__name__)

# Valid escalation options
ESCALATION_OPTIONS = {
    "reassign": "🔄 Fahrer neu zuweisen",
    "pause": "⏸️ Fahrt pausieren",
    "cancel": "❌ Fahrt stornieren",
    "acknowledge": "👁️ Zur Kenntnis nehmen",
    "resolve": "✅ Als gelöst markieren",
}

# Valid trigger reasons
TRIGGER_REASONS = {"timeout", "manual", "system"}


async def create_escalation(
    trip_id: int,
    trigger_reason: str,
    trigger_detail: str | None = None,
) -> Escalation:
    """Create a new escalation for a trip.

    Args:
        trip_id: The trip ID to escalate.
        trigger_reason: One of 'timeout', 'manual', 'system'.
        trigger_detail: Human-readable reason (e.g. "30 min ohne Status-Update").

    Returns:
        The created Escalation instance.

    Raises:
        ValueError: If trigger_reason is invalid or escalation is disabled.
    """
    if not config.ESCALATION_ENABLED:
        raise ValueError("Escalation system is disabled.")

    if trigger_reason not in TRIGGER_REASONS:
        raise ValueError(
            f"Invalid trigger_reason '{trigger_reason}'. "
            f"Must be one of: {', '.join(sorted(TRIGGER_REASONS))}"
        )

    # Verify trip exists
    trip = await Trip.get_or_none(id=trip_id)
    if trip is None:
        raise ValueError(f"Trip {trip_id} not found.")

    escalation = await Escalation.create(
        trip_id=trip_id,
        trigger_reason=trigger_reason,
        trigger_detail=trigger_detail,
        status="open",
    )

    logger.info(
        "escalation_created",
        escalation_id=escalation.id,
        trip_id=trip_id,
        trigger_reason=trigger_reason,
    )

    return escalation


async def process_escalation_option(
    escalation_id: int,
    option: str,
    telegram_id: int,
    resolution_note: str | None = None,
) -> Escalation:
    """Process an escalation option chosen by the chef.

    Args:
        escalation_id: The escalation to act on.
        option: One of 'reassign', 'pause', 'cancel', 'acknowledge', 'resolve'.
        telegram_id: The chef's Telegram ID making the decision.
        resolution_note: Optional note about the resolution.

    Returns:
        The updated Escalation instance.

    Raises:
        ValueError: If the option is invalid or the escalation is already resolved.
    """
    if option not in ESCALATION_OPTIONS:
        raise ValueError(
            f"Invalid option '{option}'. "
            f"Must be one of: {', '.join(ESCALATION_OPTIONS.keys())}"
        )

    escalation = await Escalation.get_or_none(id=escalation_id)
    if escalation is None:
        raise ValueError(f"Escalation {escalation_id} not found.")

    if escalation.status == "resolved":
        raise ValueError(f"Escalation {escalation_id} is already resolved.")

    now = datetime.now(UTC)

    # Update escalation based on chosen option
    if option == "acknowledge":
        escalation.status = "acknowledged"
        escalation.acknowledged_at = now
    elif option in ("reassign", "pause", "cancel", "resolve"):
        escalation.status = "resolved"
        escalation.resolved_at = now
    # For 'resolve', 'reassign', 'pause', 'cancel' — all resolve the escalation

    escalation.chosen_option = option
    escalation.resolved_by_telegram_id = telegram_id
    escalation.resolution_note = resolution_note
    await escalation.save()

    # Apply option-specific actions on the trip
    trip = await escalation.trip
    if option == "cancel":
        trip.status = "storniert"
        await trip.save()
        logger.info("trip_cancelled_via_escalation", trip_id=trip.id, escalation_id=escalation_id)
    elif option == "reassign":
        # Reset trip to 'geplant' so dispatch can reassign
        trip.status = "geplant"
        trip.driver_id = None
        await trip.save()
        logger.info("trip_reassigned_via_escalation", trip_id=trip.id, escalation_id=escalation_id)
    elif option == "pause":
        # Set trip to 'problem' state for pausing
        trip.status = "problem"
        await trip.save()
        logger.info("trip_paused_via_escalation", trip_id=trip.id, escalation_id=escalation_id)

    logger.info(
        "escalation_option_processed",
        escalation_id=escalation_id,
        option=option,
        telegram_id=telegram_id,
    )

    return escalation


async def get_open_escalations(limit: int = 20) -> list[Escalation]:
    """Return all open (unresolved) escalations, newest first.

    Args:
        limit: Maximum number of results (default 20).
    """
    return await (
        Escalation.filter(status__not="resolved")
        .order_by("-created_at")
        .limit(limit)
        .prefetch_related("trip")
        .all()
    )


async def get_escalation_log(
    trip_id: int | None = None,
    limit: int = 50,
) -> list[Escalation]:
    """Query the escalation audit log.

    Args:
        trip_id: If provided, filter to a specific trip. If None, return all.
        limit: Maximum number of results (default 50).

    Returns:
        List of Escalation instances, newest first.
    """
    qs = Escalation.all().order_by("-created_at").prefetch_related("trip")

    if trip_id is not None:
        qs = qs.filter(trip_id=trip_id)

    return await qs.limit(limit).all()


async def check_timeout_escalations() -> list[Escalation]:
    """Check for trips that need timeout-based escalation.

    A trip qualifies if:
    - Status is in an active state (zugewiesen through unterwegs)
    - Its last TripEvent is older than ESCALATION_TIMEOUT_MINUTES
    - No open escalation already exists for this trip

    Returns:
        List of newly created Escalation instances.
    """
    timeout_minutes = config.ESCALATION_TIMEOUT_MINUTES
    cutoff = datetime.now(UTC) - timedelta(minutes=timeout_minutes)
    active_states = [
        "zugewiesen", "anfahrt", "angekommen",
        "patient_an_bord", "unterwegs", "abgesetzt",
    ]

    new_escalations: list[Escalation] = []

    # Find trips in active states
    trips = await Trip.filter(status__in=active_states).prefetch_related("events").all()

    for trip in trips:
        # Check if there's already an open escalation
        existing = await Escalation.filter(
            trip_id=trip.id, status__not="resolved"
        ).first()
        if existing is not None:
            continue

        # Check last event time
        events = await trip.events.all().order_by("-created_at").limit(1)
        last_activity = trip.created_at if not events else events[0].created_at

        if last_activity.replace(tzinfo=UTC) < cutoff:
            esc = await create_escalation(
                trip_id=trip.id,
                trigger_reason="timeout",
                trigger_detail=(
                    f"Kein Status-Update seit über {timeout_minutes} Minuten "
                    f"(letzte Aktivität: {last_activity.strftime('%d.%m.%Y %H:%M')})"
                ),
            )
            new_escalations.append(esc)

    return new_escalations
