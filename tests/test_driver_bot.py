"""Tests for the Driver-Bot — /heute, /pause, callback handling, morning-push.

TDD: RED phase first — all tests expect features that exist or need fixing.
"""

import os
import sqlite3
from datetime import date, datetime, time, timedelta
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest


# ── SQLite time adapter ────────────────────────────────────────────────────

def _adapt_time(t: time) -> str:
    if t.tzinfo is not None:
        t = t.replace(tzinfo=None)
    return t.isoformat()


def _convert_time(raw: bytes) -> time:
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    return time.fromisoformat(text)


sqlite3.register_adapter(time, _adapt_time)
sqlite3.register_converter("time", _convert_time)


# ── Env setup ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_env():
    os.environ.setdefault("PATIENT_BOT_TOKEN", "test_patient_token")
    os.environ.setdefault("DRIVER_BOT_TOKEN", "test_driver_token")
    os.environ.setdefault("CHEF_BOT_TOKEN", "test_chef_token")
    os.environ.setdefault("DEEPSEEK_API_KEY", "test_deepseek_key")
    os.environ.setdefault("ADMIN_TELEGRAM_IDS", "")


# ── DB helpers ─────────────────────────────────────────────────────────────

async def _init_test_db():
    from tortoise import Tortoise
    await Tortoise.init(
        db_url="sqlite://:memory:",
        modules={"models": ["krankenfahrt.models.schema"]},
    )
    await Tortoise.generate_schemas()


async def _close_test_db():
    from tortoise import Tortoise
    await Tortoise.close_connections()


# ── Fixture factories ──────────────────────────────────────────────────────

def make_update(tg_id: int) -> MagicMock:
    """Create a minimal Telegram Update mock for a driver."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = tg_id
    update.message = AsyncMock()
    return update


async def create_driver(tg_id: int, name: str = "Max Fahrer") -> "Driver":
    """Create a Driver record in the test DB."""
    from krankenfahrt.models.schema import Driver
    return await Driver.create(
        telegram_id=tg_id,
        name=name,
        phone="+49123456789",
    )


async def create_trip(driver, patient, pickup: datetime, dest: str = "Charité",
                      status: str = "zugewiesen") -> "Trip":
    """Create a Trip record in the test DB."""
    from krankenfahrt.models.schema import Trip
    return await Trip.create(
        patient=patient,
        driver=driver,
        pickup_addr="Hauptstraße 1",
        dest_addr=dest,
        scheduled_pickup=pickup,
        scheduled_dropoff=pickup + timedelta(hours=1),
        status=status,
    )


async def create_patient(tg_id: int = 999001, name: str = "Anna Patient") -> "Patient":
    """Create a Patient record."""
    from krankenfahrt.models.schema import Patient
    return await Patient.create(
        telegram_id=tg_id,
        name=name,
        default_pickup_addr="Parkstraße 5",
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tests: /heute command
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_heute_unregistered_driver_shows_error():
    """/heute for an unregistered telegram ID shows an error message."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.driver_bot import cmd_heute

        update = make_update(tg_id=999999)
        await cmd_heute(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "nicht als Fahrer registriert" in text
    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_heute_no_trips_shows_free_day():
    """/heute with no trips today shows a friendly 'free day' message."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.driver_bot import cmd_heute

        driver = await create_driver(tg_id=111111, name="Max Mustermann")
        update = make_update(tg_id=111111)

        await cmd_heute(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "keine Fahrten" in text
        assert "freien Tag" in text
        assert "Max Mustermann" in text
    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_heute_with_trips_today_shows_overview():
    """/heute lists today's trips with status, times, and destinations."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.driver_bot import cmd_heute

        driver = await create_driver(tg_id=111111)
        patient = await create_patient()

        today = date.today()
        await create_trip(
            driver, patient,
            pickup=datetime(today.year, today.month, today.day, 8, 0),
            dest="Charité Berlin",
        )
        await create_trip(
            driver, patient,
            pickup=datetime(today.year, today.month, today.day, 14, 0),
            dest="Vivantes Klinikum",
            status="geplant",
        )

        update = make_update(tg_id=111111)
        await cmd_heute(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "2" in text or "Fahrten" in text
        assert "Charité" in text
        assert "Vivantes" in text
        assert "08:00" in text
        assert "14:00" in text
        assert "Schicht" in text  # shift window shown
    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_heute_shows_completed_break():
    """/heute shows completed breaks with duration."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.driver_bot import cmd_heute
        from krankenfahrt.models.schema import DriverBreak

        driver = await create_driver(tg_id=111111)
        today = date.today()

        # A completed break today
        break_start = datetime(today.year, today.month, today.day, 12, 0)
        break_end = break_start + timedelta(minutes=30)
        await DriverBreak.create(
            driver=driver,
            start_time=break_start,
            end_time=break_end,
        )

        update = make_update(tg_id=111111)
        await cmd_heute(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "Pausen" in text
        assert "12:00" in text
        assert "30 Min" in text
    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_heute_shows_active_break():
    """/heute shows an active (unfinished) break with 'läuft' indicator."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.driver_bot import cmd_heute
        from krankenfahrt.models.schema import DriverBreak

        driver = await create_driver(tg_id=111111)
        today = date.today()
        break_start = datetime(today.year, today.month, today.day, 10, 0)

        await DriverBreak.create(
            driver=driver,
            start_time=break_start,
            end_time=None,  # still active
        )

        update = make_update(tg_id=111111)
        await cmd_heute(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "Pause aktiv" in text or "läuft" in text
    finally:
        await _close_test_db()


# ═══════════════════════════════════════════════════════════════════════════
# Tests: /heute — midnight break spanning (BUGFIX)
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_heute_active_break_from_yesterday_shows_in_break_list():
    """Active break that started yesterday should appear in today's /heute overview.

    This is the bugfix test: when a driver starts a break at 23:30 and hasn't
    ended it, the next morning's /heute should show it as an active break.
    """
    await _init_test_db()
    try:
        from krankenfahrt.bots.driver_bot import cmd_heute
        from krankenfahrt.models.schema import DriverBreak

        driver = await create_driver(tg_id=111111)

        # Break started yesterday at 23:30, still active
        yesterday = datetime.now() - timedelta(days=1)
        break_start = yesterday.replace(hour=23, minute=30, second=0, microsecond=0)
        await DriverBreak.create(
            driver=driver,
            start_time=break_start,
            end_time=None,
        )

        update = make_update(tg_id=111111)
        await cmd_heute(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        # The active break should be mentioned
        assert "Pause aktiv" in text or "läuft" in text
        # Even though it started yesterday, it should show in the break list
        assert "23:30" in text
    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_heute_break_completed_across_midnight_shows_correct_duration():
    """Break 23:30→00:15 should show 45 min duration, not appear broken."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.driver_bot import cmd_heute
        from krankenfahrt.models.schema import DriverBreak

        driver = await create_driver(tg_id=111111)

        # Simulate: break started yesterday 23:30, ended today 00:15
        yesterday = datetime.now() - timedelta(days=1)
        break_start = yesterday.replace(hour=23, minute=30, second=0, microsecond=0)
        today_midnight = break_start.replace(hour=0, minute=15, second=0) + timedelta(days=1)
        await DriverBreak.create(
            driver=driver,
            start_time=break_start,
            end_time=today_midnight,
        )

        update = make_update(tg_id=111111)
        await cmd_heute(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        # Duration should be 45 minutes (23:30 → 00:15)
        assert "45 Min" in text
    finally:
        await _close_test_db()


# ═══════════════════════════════════════════════════════════════════════════
# Tests: /pause command
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_pause_unregistered_driver_error():
    """/pause for unregistered driver shows error."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.driver_bot import cmd_pause

        update = make_update(tg_id=999999)
        await cmd_pause(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "nicht als Fahrer registriert" in text
    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_pause_start_creates_break():
    """/pause with no active break creates a new DriverBreak."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.driver_bot import cmd_pause
        from krankenfahrt.models.schema import DriverBreak

        driver = await create_driver(tg_id=111111)
        update = make_update(tg_id=111111)

        await cmd_pause(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "Pause gestartet" in text

        # Verify DB record
        breaks = await DriverBreak.filter(driver_id=driver.id)
        assert len(breaks) == 1
        assert breaks[0].end_time is None
    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_pause_end_stops_active_break():
    """/pause with active break ends it and shows duration."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.driver_bot import cmd_pause
        from krankenfahrt.models.schema import DriverBreak

        driver = await create_driver(tg_id=111111)

        # Create an active break started 30 minutes ago
        start = datetime.now() - timedelta(minutes=30)
        await DriverBreak.create(driver=driver, start_time=start, end_time=None)

        update = make_update(tg_id=111111)
        await cmd_pause(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "Pause beendet" in text
        assert "Minuten" in text

        # Verify DB: break now has end_time
        breaks = await DriverBreak.filter(driver_id=driver.id)
        assert len(breaks) == 1
        # end_time should be set (within last few seconds)
        assert breaks[0].end_time is not None
    finally:
        await _close_test_db()


# ═══════════════════════════════════════════════════════════════════════════
# Tests: callback data encoding
# ═══════════════════════════════════════════════════════════════════════════


def test_pack_callback_encodes_trip_and_trigger():
    """_pack_callback produces correct format."""
    from krankenfahrt.bots.driver_bot import _pack_callback
    result = _pack_callback(42, "losfahren")
    assert result == "trip:42:losfahren"


def test_unpack_callback_decodes_valid_data():
    """_unpack_callback returns (trip_id, trigger) for valid data."""
    from krankenfahrt.bots.driver_bot import _unpack_callback
    result = _unpack_callback("trip:99:abschliessen")
    assert result == (99, "abschliessen")


def test_unpack_callback_returns_none_for_malformed():
    """_unpack_callback returns None for bad data."""
    from krankenfahrt.bots.driver_bot import _unpack_callback
    assert _unpack_callback("bad") is None
    assert _unpack_callback("trip:abc:trigger") is None
    assert _unpack_callback("trip:1") is None
    assert _unpack_callback("other:1:trigger") is None
    assert _unpack_callback("") is None


# ═══════════════════════════════════════════════════════════════════════════
# Tests: keyboard builder
# ═══════════════════════════════════════════════════════════════════════════


def test_build_trip_keyboard_returns_buttons_for_valid_state():
    """build_trip_keyboard returns buttons for a state with transitions."""
    from krankenfahrt.bots.driver_bot import build_trip_keyboard
    kb = build_trip_keyboard("zugewiesen")
    assert kb is not None
    # zugewiesen state should have losfahren and stornieren triggers
    assert len(kb.inline_keyboard) >= 1


def test_build_trip_keyboard_returns_none_for_terminal_state():
    """build_trip_keyboard returns None for terminal states (abgeschlossen, storniert)."""
    from krankenfahrt.bots.driver_bot import build_trip_keyboard
    assert build_trip_keyboard("abgeschlossen") is None
    assert build_trip_keyboard("storniert") is None


def test_build_trip_keyboard_for_trip_embeds_trip_id():
    """build_trip_keyboard_for_trip embeds trip_id in callback data."""
    from krankenfahrt.bots.driver_bot import build_trip_keyboard_for_trip
    kb = build_trip_keyboard_for_trip(42, "zugewiesen")
    assert kb is not None
    # First button should contain the trip_id
    first_cb = kb.inline_keyboard[0][0].callback_data
    assert first_cb.startswith("trip:42:")


# ═══════════════════════════════════════════════════════════════════════════
# Tests: trip info formatter
# ═══════════════════════════════════════════════════════════════════════════


def test_format_trip_info_includes_all_fields():
    """format_trip_info includes pickup, destination, patient, vehicle type."""
    from dataclasses import dataclass
    from krankenfahrt.bots.driver_bot import format_trip_info

    @dataclass
    class FakeTrip:
        id: int = 1
        scheduled_pickup: datetime = datetime(2026, 6, 8, 10, 0)
        scheduled_dropoff: datetime = datetime(2026, 6, 8, 11, 0)
        pickup_addr: str = "Hauptstraße 1, Berlin"
        dest_addr: str = "Charité, Berlin"
        status: str = "zugewiesen"

    trip = FakeTrip()
    result = format_trip_info(trip, patient_name="Anna Patient", vehicle_type="Sitz")

    assert "Fahrt #1" in result
    assert "Anna Patient" in result
    assert "10:00" in result
    assert "Hauptstraße" in result
    assert "Charité" in result
    assert "Sitz" in result


# ═══════════════════════════════════════════════════════════════════════════
# Tests: morning-push helper — _seconds_until_next
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_seconds_until_next_returns_positive():
    """_seconds_until_next always returns a positive number."""
    from krankenfahrt.services.morning_push import _seconds_until_next
    delay = await _seconds_until_next(6, 0)
    assert delay > 0
    # Should be less than 24 hours
    assert delay < 86400


@pytest.mark.asyncio
async def test_seconds_until_next_approximately_24h_when_just_past_target():
    """When it's 06:01, _seconds_until_next(6,0) should be ~23h 59m."""
    from krankenfahrt.services.morning_push import _seconds_until_next
    # Patch datetime.now to return 06:01
    fake_now = datetime.now().replace(hour=6, minute=1, second=0, microsecond=0)
    with patch("krankenfahrt.services.morning_push.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        # Need to let timedelta work normally
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
        delay = await _seconds_until_next(6, 0)
    # Should be roughly 23h 59m = 86340 seconds
    assert 86000 < delay < 86400


# ═══════════════════════════════════════════════════════════════════════════
# Tests: morning-push send
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_send_morning_push_skips_drivers_without_telegram_id():
    """Morning-push skips drivers that have no telegram_id."""
    await _init_test_db()
    try:
        from krankenfahrt.services.morning_push import send_morning_push
        from krankenfahrt.models.schema import Driver, Trip, Patient

        # Driver with telegram_id=None (should be skipped)
        driver = await Driver.create(
            telegram_id=0,  # No valid telegram
            name="Kein Telegram",
            phone="+49000",
        )
        patient = await Patient.create(
            telegram_id=999001,
            name="Test Patient",
            default_pickup_addr="Home",
        )
        today = date.today()
        await Trip.create(
            patient=patient,
            driver=driver,
            pickup_addr="Home",
            dest_addr="Klinik",
            scheduled_pickup=datetime(today.year, today.month, today.day, 9, 0),
            status="zugewiesen",
        )

        # Mock the telegram app
        mock_app = MagicMock()
        mock_app.bot = AsyncMock()

        notified = await send_morning_push(mock_app)
        # Should not have sent any messages
        assert notified == 0
        # bot.send_message should not have been called
        mock_app.bot.send_message.assert_not_called()
    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_send_morning_push_notifies_driver_with_trip():
    """Morning-push sends message to driver with today's trips."""
    await _init_test_db()
    try:
        from krankenfahrt.services.morning_push import send_morning_push, _pushed_today
        from krankenfahrt.models.schema import Driver, Trip, Patient

        # Clear push tracking
        _pushed_today.clear()

        driver = await Driver.create(
            telegram_id=111111,
            name="Max Fahrer",
            phone="+49123",
        )
        patient = await Patient.create(
            telegram_id=999001,
            name="Anna Patient",
            default_pickup_addr="Home",
        )
        today = date.today()
        await Trip.create(
            patient=patient,
            driver=driver,
            pickup_addr="Home",
            dest_addr="Charité Berlin",
            scheduled_pickup=datetime(today.year, today.month, today.day, 8, 0),
            scheduled_dropoff=datetime(today.year, today.month, today.day, 9, 0),
            status="zugewiesen",
        )

        mock_app = MagicMock()
        mock_app.bot = AsyncMock()

        notified = await send_morning_push(mock_app)

        assert notified == 1
        mock_app.bot.send_message.assert_called_once()
        call_args = mock_app.bot.send_message.call_args
        assert call_args[1]["chat_id"] == 111111
        text = call_args[1]["text"]
        assert "Max Fahrer" in text
        assert "Charité" in text
        assert "08:00" in text
    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_send_morning_push_is_idempotent():
    """Calling send_morning_push twice doesn't send duplicate messages."""
    await _init_test_db()
    try:
        from krankenfahrt.services.morning_push import send_morning_push, _pushed_today
        from krankenfahrt.models.schema import Driver, Trip, Patient

        _pushed_today.clear()

        driver = await Driver.create(
            telegram_id=111111, name="Max Fahrer", phone="+49123",
        )
        patient = await Patient.create(
            telegram_id=999001, name="Anna Patient", default_pickup_addr="Home",
        )
        today = date.today()
        await Trip.create(
            patient=patient, driver=driver,
            pickup_addr="Home", dest_addr="Charité Berlin",
            scheduled_pickup=datetime(today.year, today.month, today.day, 8, 0),
            status="zugewiesen",
        )

        mock_app = MagicMock()
        mock_app.bot = AsyncMock()

        # First call — should notify
        n1 = await send_morning_push(mock_app)
        assert n1 == 1

        # Reset mock to check second call
        mock_app.bot.send_message.reset_mock()

        # Second call — should skip (already pushed)
        n2 = await send_morning_push(mock_app)
        assert n2 == 0
        mock_app.bot.send_message.assert_not_called()
    finally:
        await _close_test_db()


# ═══════════════════════════════════════════════════════════════════════════
# Tests: /start command
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_start_registered_driver_shows_welcome_back():
    """/start for a known driver shows 'Willkommen zurück' with name."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.driver_bot import cmd_start

        driver = await create_driver(tg_id=111111, name="Bernd Lenker")
        update = make_update(tg_id=111111)

        await cmd_start(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "Willkommen zurück" in text
        assert "Bernd Lenker" in text
        assert "/heute" in text
    finally:
        await _close_test_db()


@pytest.mark.asyncio
async def test_start_unregistered_driver_shows_error():
    """/start for unknown driver shows registration error."""
    await _init_test_db()
    try:
        from krankenfahrt.bots.driver_bot import cmd_start

        update = make_update(tg_id=999999)
        await cmd_start(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert "nicht als Fahrer registriert" in text
    finally:
        await _close_test_db()
