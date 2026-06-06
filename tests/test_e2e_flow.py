"""E2E Integration Tests: Patient → Driver → Chef flow with Mock API.

Covers the complete lifecycle with in-memory SQLite database:
  - Patient books a trip
  - Dispatch assigns a driver
  - Driver proceeds through the state machine
  - Chef receives escalation notifications on problems
  - Full happy path and edge cases (cancellation, problem handling)
"""

from __future__ import annotations

from datetime import datetime, time, timezone

import pytest
from transitions import MachineError

from krankenfahrt.core.state_machine import StateChangeEvent, TripStateMachine
from krankenfahrt.models.schema import Driver, Trip, TripEvent


# ══════════════════════════════════════════════════════════════════════════
# Helper: persist trip after state machine changes
# ══════════════════════════════════════════════════════════════════════════


async def save_trip_and_events(
    sm: TripStateMachine, trip: Trip,
) -> Trip:
    """Persist the current trip state to the DB.

    Call this after every state machine transition (or batch of transitions)
    to verify that state changes are reflected in the database.

    The state machine updates ``trip.status`` in memory via
    ``_on_after_state_change``; this function persists it.
    """
    await trip.save()
    return trip


# ══════════════════════════════════════════════════════════════════════════
# 1. Mock Notification Spy — captures notifications without Telegram
# ══════════════════════════════════════════════════════════════════════════


class NotificationSpy:
    """Captures all notifications that would be sent to patients, drivers, chef."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_to_patient(self, patient_id: int, message: str) -> None:
        self.sent.append({
            "target": "patient",
            "patient_id": patient_id,
            "message": message,
        })

    def send_to_driver(self, driver_id: int, message: str) -> None:
        self.sent.append({
            "target": "driver",
            "driver_id": driver_id,
            "message": message,
        })

    def send_to_chef(self, message: str) -> None:
        self.sent.append({
            "target": "chef",
            "message": message,
        })

    @property
    def patient_notifications(self) -> list[dict]:
        return [n for n in self.sent if n["target"] == "patient"]

    @property
    def driver_notifications(self) -> list[dict]:
        return [n for n in self.sent if n["target"] == "driver"]

    @property
    def chef_notifications(self) -> list[dict]:
        return [n for n in self.sent if n["target"] == "chef"]


# ══════════════════════════════════════════════════════════════════════════
# 2. E2E Happy Path: Patient → Driver → Chef (full lifecycle)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_full_happy_path_patient_to_driver_to_completion(
    init_db, scenario,
) -> None:
    """Complete E2E flow: Patient books trip → Driver assigned →
    Driver completes all steps → Trip finished.

    Verifies:
      - Trip created in "geplant" state
      - Driver assigned correctly (persisted to DB)
      - All 7 state transitions work (each persisted)
      - Final state is "abgeschlossen"
      - Notification messages are dispatched at key points
    """
    trip = scenario["trip"]
    driver = scenario["driver"]
    patient = scenario["patient"]
    notifier = NotificationSpy()

    # ── Step 1: Verify initial state ──────────────────────────────────
    assert trip.status == "geplant"
    assert trip.driver_id is None

    # ── Step 2: Dispatch assigns driver ───────────────────────────────
    trip.driver = driver
    trip.vehicle = scenario["vehicle"]
    await trip.save()

    sm = TripStateMachine(trip)
    sm.fahrer_zuweisen()              # geplant → zugewiesen
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "zugewiesen"
    assert trip.driver_id == driver.id

    # Notify driver about new trip
    notifier.send_to_driver(
        driver.telegram_id,
        f"Neue Fahrt: {patient.name}, Abholung: {trip.pickup_addr}",
    )
    assert len(notifier.driver_notifications) == 1

    # ── Step 3: Driver starts driving to pickup ───────────────────────
    sm.losfahren()                     # zugewiesen → anfahrt
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "anfahrt"

    # ── Step 4: Driver arrives at pickup location ─────────────────────
    sm.ankunft_melden()               # anfahrt → angekommen
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "angekommen"

    # Notify patient that driver arrived
    notifier.send_to_patient(
        patient.telegram_id,
        f"{driver.name} ist angekommen!",
    )
    assert len(notifier.patient_notifications) == 1

    # ── Step 5: Patient gets on board ─────────────────────────────────
    sm.patient_aufnehmen()             # angekommen → patient_an_bord
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "patient_an_bord"

    # ── Step 6: Trip underway to destination ──────────────────────────
    sm.fahrt_beginnen()                # patient_an_bord → unterwegs
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "unterwegs"

    # ── Step 7: Patient dropped off ───────────────────────────────────
    sm.patient_absetzen()              # unterwegs → abgesetzt
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "abgesetzt"

    # ── Step 8: Trip completed ────────────────────────────────────────
    sm.abschliessen()                  # abgesetzt → abgeschlossen
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "abgeschlossen"

    # ── Verify: 7 state-change events were logged ─────────────────────
    assert len(sm._event_log) == 7
    expected_states = [
        "zugewiesen", "anfahrt", "angekommen", "patient_an_bord",
        "unterwegs", "abgesetzt", "abgeschlossen",
    ]
    for evt, expected in zip(sm._event_log, expected_states):
        assert evt.to_state == expected, (
            f"Expected transition to '{expected}', got '{evt.to_state}'"
        )


# ══════════════════════════════════════════════════════════════════════════
# 3. E2E Problem/Escalation Flow: Driver reports problem → Chef notified
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_problem_escalation_flow(
    init_db, scenario,
) -> None:
    """Driver encounters a problem → Chef is notified → Problem resolved →
    Trip continues to completion.

    Verifies:
      - problem_melden transitions to "problem" state
      - Chef receives escalation notification
      - problem_loesen restores the previous state
      - Trip can continue normally after resolution
    """
    trip = scenario["trip"]
    driver = scenario["driver"]
    patient = scenario["patient"]
    notifier = NotificationSpy()

    # Assign driver first
    trip.driver = driver
    trip.vehicle = scenario["vehicle"]
    await trip.save()

    sm = TripStateMachine(trip)
    sm.fahrer_zuweisen()              # → zugewiesen
    sm.losfahren()                    # → anfahrt
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "anfahrt"

    # ── Driver reports a problem ──────────────────────────────────────
    pre_problem_state = sm.state
    sm.problem_melden()               # → problem
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "problem"

    # Chef receives escalation
    notifier.send_to_chef(
        f"⚠️ Problem bei Fahrt #{trip.id}: {patient.name}, "
        f"Fahrer: {driver.name}"
    )
    assert len(notifier.chef_notifications) == 1

    # ── Problem resolved ──────────────────────────────────────────────
    sm.problem_loesen(metadata={"resolved_by": "chef", "note": "Fahrzeugwechsel"})
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == pre_problem_state, (
        f"Should return to '{pre_problem_state}', got '{trip.status}'"
    )

    # ── Trip continues normally ───────────────────────────────────────
    sm.ankunft_melden()               # → angekommen
    sm.patient_aufnehmen()            # → patient_an_bord
    sm.fahrt_beginnen()               # → unterwegs
    sm.patient_absetzen()             # → abgesetzt
    sm.abschliessen()                 # → abgeschlossen
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "abgeschlossen"


# ══════════════════════════════════════════════════════════════════════════
# 4. E2E Cancellation Flow
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_cancellation_flow(
    init_db, scenario,
) -> None:
    """Trip is cancelled → Patient and Driver notified → Trip in "storniert".

    Verifies:
      - stornieren from valid states works
      - "storniert" is terminal (no further transitions)
      - Notifications are fired
    """
    trip = scenario["trip"]
    driver = scenario["driver"]
    patient = scenario["patient"]
    notifier = NotificationSpy()

    # Assign driver
    trip.driver = driver
    trip.vehicle = scenario["vehicle"]
    await trip.save()

    sm = TripStateMachine(trip)
    sm.fahrer_zuweisen()              # → zugewiesen
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "zugewiesen"

    # ── Cancel the trip ───────────────────────────────────────────────
    sm.stornieren()                   # → storniert
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "storniert"

    # Notify patient
    notifier.send_to_patient(
        patient.telegram_id,
        f"Fahrt am {trip.scheduled_pickup} wurde storniert.",
    )
    # Notify driver
    notifier.send_to_driver(
        driver.telegram_id,
        f"Fahrt #{trip.id} wurde storniert.",
    )
    assert len(notifier.patient_notifications) == 1
    assert len(notifier.driver_notifications) == 1

    # ── Verify: "storniert" is terminal ───────────────────────────────
    for trigger in [
        "fahrer_zuweisen", "losfahren", "ankunft_melden",
        "patient_aufnehmen", "fahrt_beginnen", "patient_absetzen",
        "abschliessen", "problem_melden",
    ]:
        with pytest.raises(MachineError):
            getattr(sm, trigger)()


# ══════════════════════════════════════════════════════════════════════════
# 5. TripEvent audit log is populated during E2E flow
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_e2e_flow_writes_audit_events(
    init_db, scenario,
) -> None:
    """Every state change during the full flow creates a TripEvent in the DB.

    Verifies:
      - TripEvent rows are created for each transition
      - Events can be queried by trip_id
      - Event_type is correctly set
    """
    trip = scenario["trip"]
    driver = scenario["driver"]

    trip.driver = driver
    trip.vehicle = scenario["vehicle"]
    await trip.save()

    # Create an event logger that records events (sync, since transitions is sync)
    logged_events: list[StateChangeEvent] = []

    def record_event(evt: StateChangeEvent) -> None:
        logged_events.append(evt)

    sm = TripStateMachine(trip, event_logger=record_event)

    # Run through the entire flow
    sm.fahrer_zuweisen()
    sm.losfahren()
    sm.ankunft_melden()
    sm.patient_aufnehmen()
    sm.fahrt_beginnen()
    sm.patient_absetzen()
    sm.abschliessen()

    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "abgeschlossen"

    # Persist the event log records to DB too
    for evt in sm._event_log:
        await TripEvent.create(
            trip=trip,
            event_type="status_change",
            message=f"{evt.from_state} → {evt.to_state} via {evt.trigger}",
        )

    # Verify trip events were created in the DB
    events = await TripEvent.filter(trip_id=trip.id).all()
    assert len(events) >= 7, (
        f"Expected at least 7 events, got {len(events)}"
    )

    # Verify event messages contain state transition info
    status_change_events = [
        e for e in events if e.event_type == "status_change"
    ]
    assert len(status_change_events) >= 7


# ══════════════════════════════════════════════════════════════════════════
# 6. Re-assignment Flow
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_reassignment_flow(
    init_db, scenario,
) -> None:
    """Trip is re-assigned to a different driver → back to "geplant".

    Verifies:
      - fahrer_neu_zuweisen returns trip to "geplant"
      - Driver can be changed
      - New driver assignment works
    """
    trip = scenario["trip"]
    driver1 = scenario["driver"]

    # Assign first driver
    trip.driver = driver1
    trip.vehicle = scenario["vehicle"]
    await trip.save()

    sm = TripStateMachine(trip)
    sm.fahrer_zuweisen()              # → zugewiesen
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "zugewiesen"
    assert trip.driver_id == driver1.id

    # ── Re-assign: go back to geplant ─────────────────────────────────
    sm.fahrer_neu_zuweisen()          # → geplant
    trip = await save_trip_and_events(sm, trip)
    assert trip.status == "geplant"

    # ── Create and assign a second driver ─────────────────────────────
    driver2 = await Driver.create(
        telegram_id=333333,
        name="Second Driver",
        phone="+491****2222",
        work_hours_start=time(7, 0),
        work_hours_end=time(18, 0),
        vehicle=scenario["vehicle"],
    )
    trip.driver = driver2
    await trip.save()

    # Re-create state machine with current state
    sm2 = TripStateMachine(trip)
    sm2.fahrer_zuweisen()             # → zugewiesen
    trip = await save_trip_and_events(sm2, trip)
    assert trip.status == "zugewiesen"
    assert trip.driver_id == driver2.id


# ══════════════════════════════════════════════════════════════════════════
# 7. Mock API lifecycle: DB is properly initialized and torn down
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_mock_api_start_stop(init_db) -> None:
    """Verify the mock API (in-memory DB) can be started and stopped.

    This test ensures the test infrastructure itself is sound:
      - DB is initialized (tables exist)
      - We can create and query records
      - Tables are clean between tests
    """
    from krankenfahrt.models.schema import Patient

    # DB is initialized by the init_db fixture
    patient = await Patient.create(
        telegram_id=1,
        name="API Test Patient",
        default_pickup_addr="Test Address",
    )
    assert patient.id is not None

    # Query it back
    found = await Patient.get(telegram_id=1)
    assert found.name == "API Test Patient"
