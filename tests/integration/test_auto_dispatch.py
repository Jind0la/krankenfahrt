"""Tests for auto-assignment handler — TDD: RED phase first.

Tests cover:
- Trip with matching driver → auto-assigned + notification sent
- Trip with no matching driver → escalation to dispatcher
- Manual assignment flow remains unchanged
- Edge cases: no drivers, driver already busy, vehicle mismatch, P-Schein requirement
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure env vars for import
os.environ.setdefault("PATIENT_BOT_TOKEN", "test_patient_token")
os.environ.setdefault("DRIVER_BOT_TOKEN", "test_driver_token")
os.environ.setdefault("CHEF_BOT_TOKEN", "test_chef_token")
os.environ.setdefault("DEEPSEEK_API_KEY", "test_deepseek_key")


# ── Test fixtures ──────────────────────────────────────────────────────────

@dataclass
class FakePatient:
    """Minimal patient stub for dispatch tests."""
    id: int = 1
    vehicle_type: str = "Sitz"
    special_needs: Optional[str] = None


@dataclass
class FakeVehicle:
    """Minimal vehicle stub."""
    id: int = 1
    vehicle_type: str = "Sitz"


@dataclass
class FakeDriver:
    """Minimal driver stub matching the interface the dispatch engine expects."""
    id: int = 1
    telegram_id: int = 1001
    name: str = "Max Mustermann"
    phone: str = "+49123456789"
    p_schein: bool = False
    work_hours_start: time = field(default_factory=lambda: time(7, 0))
    work_hours_end: time = field(default_factory=lambda: time(16, 0))
    work_days: str = "Mo,Di,Mi,Do,Fr"
    active: bool = True
    vehicle: Optional[FakeVehicle] = None


@dataclass
class FakeTrip:
    """Minimal trip stub matching what the dispatch engine and handler need."""
    id: int = 1
    status: str = "geplant"
    scheduled_pickup: datetime = field(default_factory=lambda: datetime(2026, 6, 8, 10, 0))
    pickup_addr: str = "Hauptstraße 1, Berlin"
    dest_addr: str = "Charité, Berlin"

    # These are async in Tortoise; in tests they are simple attributes
    patient: FakePatient = field(default_factory=FakePatient)
    driver: Optional[FakeDriver] = None
    vehicle: Optional[FakeVehicle] = None

    async def save(self):
        """Mock Tortoise .save()."""
        pass


# ── Helpers ────────────────────────────────────────────────────────────────

def make_driver(**kwargs) -> FakeDriver:
    """Create a driver with overrides."""
    defaults = {
        "id": 1,
        "telegram_id": 1001,
        "name": "Max Mustermann",
        "phone": "+49123456789",
        "p_schein": False,
        "active": True,
        "vehicle": FakeVehicle(vehicle_type="Sitz"),
    }
    defaults.update(kwargs)
    return FakeDriver(**defaults)


def make_trip(**kwargs) -> FakeTrip:
    """Create a trip with overrides."""
    defaults = {
        "id": 1,
        "status": "geplant",
        "scheduled_pickup": datetime(2026, 6, 8, 10, 0),
        "patient": FakePatient(vehicle_type="Sitz"),
    }
    defaults.update(kwargs)
    return FakeTrip(**defaults)


# ── Notification Spy ───────────────────────────────────────────────────────

class NotificationSpy:
    """Captures all sent notifications for assertion."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_to_driver(self, driver_id: int, message: str) -> None:
        self.sent.append({"target": "driver", "driver_id": driver_id, "message": message})

    async def send_to_chef(self, message: str) -> None:
        self.sent.append({"target": "chef", "message": message})


# ── Tests: Match scenario ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_assign_when_driver_matches():
    """When a matching driver exists, the trip is assigned and driver notified."""
    from krankenfahrt.core.auto_dispatch import AutoDispatchHandler

    driver = make_driver(id=42, name="Anna Fahrer", telegram_id=42001)
    trip = make_trip(id=99)

    # Mock the dispatch engine to always return this driver
    mock_engine = MagicMock()
    mock_engine.find_best_driver = AsyncMock(return_value=MagicMock(
        driver=driver,
        trip=trip,
        distance_km=3.5,
        score=3.5,
    ))

    # Mock finding available drivers
    mock_get_drivers = AsyncMock(return_value=[driver])

    notifier = NotificationSpy()
    handler = AutoDispatchHandler(
        engine=mock_engine,
        notifier=notifier,
        get_available_drivers=mock_get_drivers,
    )

    result = await handler.handle_new_trip(trip)

    # Assert match found
    assert result.matched is True
    assert result.assigned_driver_id == 42
    assert result.escalation_reason is None

    # Assert driver assigned to trip
    assert trip.driver is not None
    assert trip.driver.id == 42
    assert trip.status == "zugewiesen"

    # Assert notification sent to driver
    assert len(notifier.sent) == 1
    assert notifier.sent[0]["target"] == "driver"
    assert notifier.sent[0]["driver_id"] == 42001
    assert "Anna Fahrer" in notifier.sent[0]["message"] or "Neue Fahrt" in notifier.sent[0]["message"]

    # Assert engine was called
    mock_engine.find_best_driver.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_assign_notifies_driver_with_trip_details():
    """Driver notification includes trip details (pickup, destination, patient)."""
    from krankenfahrt.core.auto_dispatch import AutoDispatchHandler

    patient = FakePatient(vehicle_type="Sitz")
    driver = make_driver(id=7, name="Bernd Lenker")
    trip = make_trip(
        id=200,
        pickup_addr="Alexanderplatz 1, Berlin",
        dest_addr="Vivantes Klinikum, Berlin",
        patient=patient,
    )

    mock_engine = MagicMock()
    mock_engine.find_best_driver = AsyncMock(return_value=MagicMock(
        driver=driver,
        trip=trip,
        distance_km=2.1,
        score=2.1,
    ))

    notifier = NotificationSpy()
    handler = AutoDispatchHandler(
        engine=mock_engine,
        notifier=notifier,
        get_available_drivers=AsyncMock(return_value=[driver]),
    )

    await handler.handle_new_trip(trip)

    msg = notifier.sent[0]["message"]
    assert "Alexanderplatz" in msg
    assert "Vivantes" in msg


# ── Tests: No-match / escalation scenario ──────────────────────────────────

@pytest.mark.asyncio
async def test_escalate_when_no_driver_matches():
    """When no driver matches, escalate to dispatcher without assigning."""
    from krankenfahrt.core.auto_dispatch import AutoDispatchHandler

    trip = make_trip(id=300)

    # Mock engine returns None (no match)
    mock_engine = MagicMock()
    mock_engine.find_best_driver = AsyncMock(return_value=None)

    notifier = NotificationSpy()
    handler = AutoDispatchHandler(
        engine=mock_engine,
        notifier=notifier,
        get_available_drivers=AsyncMock(return_value=[]),
    )

    result = await handler.handle_new_trip(trip)

    # Assert no match
    assert result.matched is False
    assert result.assigned_driver_id is None
    assert result.escalation_reason is not None

    # Trip stays unassigned
    assert trip.driver is None
    assert trip.status == "geplant"  # unchanged

    # Escalation sent to chef
    assert len(notifier.sent) == 1
    assert notifier.sent[0]["target"] == "chef"
    assert "Eskalation" in notifier.sent[0]["message"] or "300" in notifier.sent[0]["message"]


@pytest.mark.asyncio
async def test_escalate_when_no_drivers_available():
    """When there are zero active drivers, escalate immediately."""
    from krankenfahrt.core.auto_dispatch import AutoDispatchHandler

    trip = make_trip(id=400)
    mock_engine = MagicMock()
    mock_engine.find_best_driver = AsyncMock(return_value=None)

    notifier = NotificationSpy()
    handler = AutoDispatchHandler(
        engine=mock_engine,
        notifier=notifier,
        get_available_drivers=AsyncMock(return_value=[]),
    )

    result = await handler.handle_new_trip(trip)

    assert result.matched is False
    assert (
        "kein" in result.escalation_reason.lower()
        and "fahrer" in result.escalation_reason.lower()
    )


# ── Tests: Manual assignment not affected ──────────────────────────────────

@pytest.mark.asyncio
async def test_manual_assignment_still_works_independently():
    """Manual driver assignment (chef sets driver directly) is unaffected by auto-dispatch."""
    # This is a doc-test style: the auto_dispatch module does NOT change
    # the Trip model or the state machine. Manual assignment via
    # trip.driver = some_driver; trip.status = "zugewiesen"; await trip.save()
    # continues to work exactly as before.
    trip = make_trip(status="geplant")
    driver = make_driver(id=99)

    # Simulate manual assignment
    trip.driver = driver
    trip.status = "zugewiesen"

    assert trip.driver.id == 99
    assert trip.status == "zugewiesen"


# ── Tests: Edge cases ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skip_auto_assign_if_already_assigned():
    """Auto-dispatch skips trips that already have a driver (already zugewiesen)."""
    from krankenfahrt.core.auto_dispatch import AutoDispatchHandler

    driver = make_driver()
    trip = make_trip(status="zugewiesen", driver=driver)

    mock_engine = MagicMock()
    notifier = NotificationSpy()
    handler = AutoDispatchHandler(
        engine=mock_engine,
        notifier=notifier,
        get_available_drivers=AsyncMock(return_value=[driver]),
    )

    result = await handler.handle_new_trip(trip)

    # Should be skipped — already assigned
    assert result.matched is True  # already has driver
    assert result.assigned_driver_id == driver.id
    mock_engine.find_best_driver.assert_not_called()
    assert len(notifier.sent) == 0


@pytest.mark.asyncio
async def test_p_schein_required_ktw():
    """KTW/Liege trips require P-Schein; driver without it is filtered out by engine."""
    # This tests that the engine correctly filters — the engine already handles this.
    # The auto-dispatch handler just calls the engine, so this is an integration
    # assurance. We verify that engine rejection → escalation.
    from krankenfahrt.core.auto_dispatch import AutoDispatchHandler

    patient = FakePatient(vehicle_type="KTW")
    trip = make_trip(patient=patient)

    mock_engine = MagicMock()
    mock_engine.find_best_driver = AsyncMock(return_value=None)

    notifier = NotificationSpy()
    handler = AutoDispatchHandler(
        engine=mock_engine,
        notifier=notifier,
        get_available_drivers=AsyncMock(return_value=[]),
    )

    result = await handler.handle_new_trip(trip)
    assert result.matched is False


@pytest.mark.asyncio
async def test_auto_dispatch_result_dataclass():
    """AutoDispatchResult carries correct fields."""
    from krankenfahrt.core.auto_dispatch import AutoDispatchResult

    r = AutoDispatchResult(matched=True, assigned_driver_id=5, escalation_reason=None)
    assert r.matched is True
    assert r.assigned_driver_id == 5

    r2 = AutoDispatchResult(matched=False, escalation_reason="Kein Fahrer verfügbar")
    assert r2.matched is False
    assert r2.assigned_driver_id is None
    assert "Kein Fahrer" in r2.escalation_reason
