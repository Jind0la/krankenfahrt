"""Tests for Chef-Bot dashboard: color-coded trips + manual assignment."""

from datetime import date, datetime

import pytest


# ---------------------------------------------------------------------------
# Helpers — pure functions testable without DB/Telegram
# ---------------------------------------------------------------------------

from krankenfahrt.bots.chef_bot import (
    STATUS_EMOJI,
    STATUS_LABEL,
    _format_trip_line,
    _build_dashboard_text,
    _build_assignment_keyboard,
)


class TestStatusEmoji:
    """Unit tests for status-to-emoji mapping."""

    def test_geplant_is_red_circle(self):
        assert STATUS_EMOJI["geplant"] == "🔴"

    def test_zugewiesen_is_yellow_circle(self):
        assert STATUS_EMOJI["zugewiesen"] == "🟡"

    def test_active_states_are_blue(self):
        for status in ("anfahrt", "angekommen", "patient_an_bord", "unterwegs"):
            assert STATUS_EMOJI[status] == "🔵", f"{status} should be blue"

    def test_abgesetzt_is_orange(self):
        assert STATUS_EMOJI["abgesetzt"] == "🟠"

    def test_abgeschlossen_is_green(self):
        assert STATUS_EMOJI["abgeschlossen"] == "🟢"

    def test_storniert_is_black(self):
        assert STATUS_EMOJI["storniert"] == "⚫"

    def test_problem_is_red(self):
        assert STATUS_EMOJI["problem"] == "🔴"

    def test_every_known_status_has_emoji(self):
        from krankenfahrt.core.state_machine import TRIP_STATES
        for state in TRIP_STATES:
            assert state in STATUS_EMOJI, f"Missing emoji for state: {state}"


class TestStatusLabel:
    """Unit tests for status-to-label mapping."""

    def test_labels_are_german(self):
        assert STATUS_LABEL["geplant"] == "Geplant"
        assert STATUS_LABEL["zugewiesen"] == "Zugewiesen"
        assert STATUS_LABEL["abgeschlossen"] == "Abgeschlossen"
        assert STATUS_LABEL["storniert"] == "Storniert"

    def test_every_known_status_has_label(self):
        from krankenfahrt.core.state_machine import TRIP_STATES
        for state in TRIP_STATES:
            assert state in STATUS_LABEL, f"Missing label for state: {state}"


class TestFormatTripLine:
    """Unit tests for single trip line formatting."""

    def test_formats_pending_trip_without_driver(self):
        trip = _FakeTrip(
            id=1,
            status="geplant",
            patient_name="Max Mustermann",
            pickup_addr="Hauptstr. 1, Berlin",
            dest_addr="Charité, Berlin",
            scheduled_pickup=datetime(2026, 6, 6, 9, 0),
            driver_name=None,
        )
        line = _format_trip_line(trip)
        assert "🔴" in line
        assert "#1" in line
        assert "Max Mustermann" in line
        assert "Hauptstr. 1" in line
        assert "Charité" in line
        assert "09:00" in line
        assert "Kein Fahrer" in line

    def test_formats_assigned_trip_with_driver(self):
        trip = _FakeTrip(
            id=2,
            status="zugewiesen",
            patient_name="Anna Schmidt",
            pickup_addr="Bahnhofstr. 5, Potsdam",
            dest_addr="Klinikum Potsdam",
            scheduled_pickup=datetime(2026, 6, 6, 14, 30),
            driver_name="Hans Müller",
        )
        line = _format_trip_line(trip)
        assert "🟡" in line
        assert "#2" in line
        assert "Anna Schmidt" in line
        assert "14:30" in line
        assert "Hans Müller" in line


class TestBuildDashboardText:
    """Unit tests for the full dashboard text assembly."""

    def test_header_includes_date(self):
        trips = []
        today = date(2026, 6, 6)
        text = _build_dashboard_text(trips, today)
        assert "06.06.2026" in text
        assert "FahrtenChef" in text or "Dashboard" in text

    def test_shows_no_trips_message_when_empty(self):
        trips = []
        today = date.today()
        text = _build_dashboard_text(trips, today)
        assert "keine Fahrten" in text.lower() or "Keine Fahrten" in text

    def test_lists_all_provided_trips(self):
        trips = [
            _FakeTrip(id=1, status="geplant", patient_name="A",
                      pickup_addr="X", dest_addr="Y",
                      scheduled_pickup=datetime(2026, 6, 6, 9, 0)),
            _FakeTrip(id=2, status="abgeschlossen", patient_name="B",
                      pickup_addr="X", dest_addr="Y",
                      scheduled_pickup=datetime(2026, 6, 6, 10, 0)),
        ]
        text = _build_dashboard_text(trips, date(2026, 6, 6))
        assert "#1" in text
        assert "#2" in text
        assert "A" in text
        assert "B" in text

    def test_summary_counts_by_status(self):
        trips = [
            _FakeTrip(id=1, status="geplant", patient_name="A",
                      pickup_addr="X", dest_addr="Y",
                      scheduled_pickup=datetime(2026, 6, 6, 9, 0)),
            _FakeTrip(id=2, status="abgeschlossen", patient_name="B",
                      pickup_addr="X", dest_addr="Y",
                      scheduled_pickup=datetime(2026, 6, 6, 10, 0)),
            _FakeTrip(id=3, status="abgeschlossen", patient_name="C",
                      pickup_addr="X", dest_addr="Y",
                      scheduled_pickup=datetime(2026, 6, 6, 11, 0)),
        ]
        text = _build_dashboard_text(trips, date(2026, 6, 6))
        assert "Geplant: 1" in text or "geplant" in text.lower()
        assert "Abgeschlossen: 2" in text or "abgeschlossen" in text.lower()


class TestBuildAssignmentKeyboard:
    """Unit tests for the inline keyboard builder."""

    def test_no_keyboard_for_assigned_trip(self):
        trip = _FakeTrip(id=1, status="zugewiesen", patient_name="X",
                         pickup_addr="A", dest_addr="B",
                         scheduled_pickup=datetime(2026,6,6,9,0),
                         driver_name="Hans")
        kb = _build_assignment_keyboard(trip, [])
        assert kb is None

    def test_no_keyboard_for_completed_trip(self):
        trip = _FakeTrip(id=1, status="abgeschlossen", patient_name="X",
                         pickup_addr="A", dest_addr="B",
                         scheduled_pickup=datetime(2026,6,6,9,0),
                         driver_name="Hans")
        kb = _build_assignment_keyboard(trip, [])
        assert kb is None

    def test_no_keyboard_for_cancelled_trip(self):
        trip = _FakeTrip(id=1, status="storniert", patient_name="X",
                         pickup_addr="A", dest_addr="B",
                         scheduled_pickup=datetime(2026,6,6,9,0))
        kb = _build_assignment_keyboard(trip, [])
        assert kb is None

    def test_keyboard_for_geplant_trip_with_drivers(self):
        trip = _FakeTrip(id=1, status="geplant", patient_name="X",
                         pickup_addr="A", dest_addr="B",
                         scheduled_pickup=datetime(2026,6,6,9,0))
        drivers = [
            _FakeDriver(id=10, name="Hans Müller"),
            _FakeDriver(id=20, name="Klaus Schmidt"),
        ]
        kb = _build_assignment_keyboard(trip, drivers)
        assert kb is not None
        assert len(kb) == 1  # one row
        assert len(kb[0]) == 2  # two buttons
        assert kb[0][0].text == "Hans Müller"
        assert "assign_1_10" in kb[0][0].callback_data
        assert kb[0][1].text == "Klaus Schmidt"
        assert "assign_1_20" in kb[0][1].callback_data

    def test_keyboard_for_geplant_trip_no_drivers(self):
        trip = _FakeTrip(id=1, status="geplant", patient_name="X",
                         pickup_addr="A", dest_addr="B",
                         scheduled_pickup=datetime(2026,6,6,9,0))
        kb = _build_assignment_keyboard(trip, [])
        assert kb is None  # No drivers to assign, so no keyboard


# ---------------------------------------------------------------------------
# Fake objects that mimic Tortoise model access patterns
# ---------------------------------------------------------------------------

class _FakeTrip:
    def __init__(self, *, id, status, patient_name, pickup_addr, dest_addr,
                 scheduled_pickup, driver_name=None, driver_id=None):
        self.id = id
        self.status = status
        self.patient_name = patient_name
        self.pickup_addr = pickup_addr
        self.dest_addr = dest_addr
        self.scheduled_pickup = scheduled_pickup
        self.driver_name = driver_name
        self.driver_id = driver_id

    @property
    def patient(self):
        return _FakePatient(self.patient_name)

    @property
    def driver(self):
        if self.driver_name:
            return _FakeDriver(id=self.driver_id, name=self.driver_name)
        return None


class _FakePatient:
    def __init__(self, name):
        self.name = name


class _FakeDriver:
    def __init__(self, id, name):
        self.id = id
        self.name = name


# ---------------------------------------------------------------------------
# Integration tests with real SQLite (Tortoise in-memory)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def init_db():
    """Initialize Tortoise ORM with in-memory SQLite for each test."""
    from tortoise import Tortoise
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["krankenfahrt.models.schema"]},
    )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest.fixture
async def seed_data():
    """Create test patients, drivers, vehicles, and trips."""
    from krankenfahrt.models.schema import (
        Patient, Driver, Vehicle,
    )

    p1 = await Patient.create(
        telegram_id=1001, name="Max Mustermann",
        default_pickup_addr="Hauptstr. 1, Berlin",
    )
    p2 = await Patient.create(
        telegram_id=1002, name="Erika Beispiel",
        default_pickup_addr="Parkweg 5, Potsdam",
    )

    v1 = await Vehicle.create(license_plate="B-KF-123", vehicle_type="Sitz")

    d1 = await Driver.create(
        telegram_id=2001, name="Hans Fahrer", phone="+491111",
        vehicle=v1,
    )
    d2 = await Driver.create(
        telegram_id=2002, name="Klaus Lenker", phone="+492222",
    )

    return {"patients": [p1, p2], "drivers": [d1, d2], "vehicles": [v1]}


@pytest.mark.asyncio
async def test_fetch_todays_trips_only(seed_data):
    """DB query returns only trips scheduled for today."""
    from krankenfahrt.models.schema import Trip, Patient
    from datetime import datetime, timedelta

    today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    await Trip.create(
        patient=seed_data["patients"][0],
        pickup_addr="H1", dest_addr="H2",
        scheduled_pickup=today,
        status="geplant",
    )
    await Trip.create(
        patient=seed_data["patients"][1],
        pickup_addr="H3", dest_addr="H4",
        scheduled_pickup=yesterday,
        status="abgeschlossen",
    )
    await Trip.create(
        patient=seed_data["patients"][0],
        pickup_addr="H5", dest_addr="H6",
        scheduled_pickup=tomorrow,
        status="geplant",
    )

    from krankenfahrt.bots.chef_bot import _fetch_todays_trips
    trips = await _fetch_todays_trips()

    assert len(trips) == 1
    assert trips[0].scheduled_pickup.date() == today.date()


@pytest.mark.asyncio
async def test_fetch_todays_trips_includes_relations(seed_data):
    """Fetched trips include patient and driver relations."""
    from krankenfahrt.models.schema import Trip
    from datetime import datetime

    today = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)

    trip = await Trip.create(
        patient=seed_data["patients"][0],
        driver=seed_data["drivers"][0],
        vehicle=seed_data["vehicles"][0],
        pickup_addr="A", dest_addr="B",
        scheduled_pickup=today,
        status="zugewiesen",
    )

    from krankenfahrt.bots.chef_bot import _fetch_todays_trips
    trips = await _fetch_todays_trips()

    assert len(trips) == 1
    t = trips[0]
    assert t.patient.name == "Max Mustermann"
    assert t.driver.name == "Hans Fahrer"


@pytest.mark.asyncio
async def test_assign_driver_updates_trip(seed_data):
    """Assigning a driver updates trip status and driver FK."""
    from krankenfahrt.models.schema import Trip
    from datetime import datetime

    today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)

    trip = await Trip.create(
        patient=seed_data["patients"][0],
        pickup_addr="A", dest_addr="B",
        scheduled_pickup=today,
        status="geplant",
    )

    from krankenfahrt.bots.chef_bot import _assign_driver
    await _assign_driver(trip.id, seed_data["drivers"][0].id)

    await trip.refresh_from_db()
    assert trip.status == "zugewiesen"
    assert trip.driver_id == seed_data["drivers"][0].id


@pytest.mark.asyncio
async def test_assign_driver_raises_for_nonexistent_trip(seed_data):
    """Assigning to a nonexistent trip raises ValueError."""
    from krankenfahrt.bots.chef_bot import _assign_driver
    with pytest.raises(ValueError, match="Trip .* nicht gefunden"):
        await _assign_driver(99999, seed_data["drivers"][0].id)


@pytest.mark.asyncio
async def test_assign_driver_raises_for_nonexistent_driver(seed_data):
    """Assigning a nonexistent driver raises ValueError."""
    from krankenfahrt.models.schema import Trip
    from datetime import datetime

    today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    trip = await Trip.create(
        patient=seed_data["patients"][0],
        pickup_addr="A", dest_addr="B",
        scheduled_pickup=today,
        status="geplant",
    )

    from krankenfahrt.bots.chef_bot import _assign_driver
    with pytest.raises(ValueError, match="Fahrer .* nicht gefunden"):
        await _assign_driver(trip.id, 99999)


@pytest.mark.asyncio
async def test_fetch_active_drivers(seed_data):
    """Fetches only active drivers."""
    from krankenfahrt.models.schema import Driver
    await Driver.create(
        telegram_id=2003, name="Inaktiv Fahrer", phone="+493333",
        active=False,
    )

    from krankenfahrt.bots.chef_bot import _fetch_active_drivers
    drivers = await _fetch_active_drivers()

    assert len(drivers) == 2
    names = {d.name for d in drivers}
    assert names == {"Hans Fahrer", "Klaus Lenker"}


@pytest.mark.asyncio
async def test_build_dashboard_text_with_real_trips(seed_data):
    """Integration test: dashboard text built from real trips."""
    from krankenfahrt.models.schema import Trip
    from datetime import datetime

    today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)

    await Trip.create(
        patient=seed_data["patients"][0],
        driver=seed_data["drivers"][0],
        pickup_addr="Hauptstr. 1, Berlin",
        dest_addr="Charité, Berlin",
        scheduled_pickup=today,
        status="zugewiesen",
    )
    await Trip.create(
        patient=seed_data["patients"][1],
        pickup_addr="Parkweg 5, Potsdam",
        dest_addr="Klinikum Potsdam",
        scheduled_pickup=today.replace(hour=14),
        status="geplant",
    )

    from krankenfahrt.bots.chef_bot import _fetch_todays_trips, _build_dashboard_text
    trips = await _fetch_todays_trips()
    text = _build_dashboard_text(trips, today.date())

    # Check both trips appear
    assert "Max Mustermann" in text
    assert "Erika Beispiel" in text
    # Check status emojis
    assert "🟡" in text  # zugewiesen
    assert "🔴" in text  # geplant
    # Check driver names
    assert "Hans Fahrer" in text
    assert "Kein Fahrer" in text
