"""Tests for LiveLocationTracker and patient bot location push logic.

Tests the full lifecycle: start → update → stop, plus error handling
for invalid coordinates, message-not-found, and blocked chats.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import BadRequest, Forbidden

from krankenfahrt.services.live_location import LiveLocationTracker, LiveLocationSession


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tracker() -> LiveLocationTracker:
    """Fresh tracker instance for each test."""
    return LiveLocationTracker()


@pytest.fixture
def mock_bot() -> AsyncMock:
    """Mock Telegram Bot with stubbed location methods."""
    bot = AsyncMock()

    # Default: send_location returns a message with message_id=42
    send_result = MagicMock()
    send_result.message_id = 42
    bot.send_location.return_value = send_result

    # Default: edit_message_live_location succeeds
    bot.edit_message_live_location.return_value = True

    # Default: stop_message_live_location succeeds
    bot.stop_message_live_location.return_value = True

    return bot


# ═══════════════════════════════════════════════════════════════════════════
# Coordinate validation tests (static — no bot needed)
# ═══════════════════════════════════════════════════════════════════════════


class TestCoordinateValidation:
    """LiveLocationTracker._validate_coordinates edge cases."""

    def test_valid_coordinates_munich(self, tracker):
        assert tracker._validate_coordinates(48.1351, 11.5820) is True

    def test_valid_coordinates_equator(self, tracker):
        assert tracker._validate_coordinates(0.0, 0.0) is True

    def test_valid_coordinates_extremes(self, tracker):
        assert tracker._validate_coordinates(90.0, 180.0) is True
        assert tracker._validate_coordinates(-90.0, -180.0) is True

    def test_invalid_latitude_too_high(self, tracker):
        assert tracker._validate_coordinates(90.1, 0.0) is False

    def test_invalid_latitude_too_low(self, tracker):
        assert tracker._validate_coordinates(-90.1, 0.0) is False

    def test_invalid_longitude_too_high(self, tracker):
        assert tracker._validate_coordinates(0.0, 180.1) is False

    def test_invalid_longitude_too_low(self, tracker):
        assert tracker._validate_coordinates(0.0, -180.1) is False


# ═══════════════════════════════════════════════════════════════════════════
# Start live location tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStartLiveLocation:
    """LiveLocationTracker.start() tests."""

    @pytest.mark.asyncio
    async def test_start_returns_message_id(self, tracker, mock_bot):
        """Starting live location returns the Telegram message ID."""
        msg_id = await tracker.start(
            bot=mock_bot,
            trip_id=1,
            chat_id=12345,
            lat=48.1351,
            lon=11.5820,
        )

        assert msg_id == 42
        mock_bot.send_location.assert_called_once_with(
            chat_id=12345,
            latitude=48.1351,
            longitude=11.5820,
            live_period=3600,
        )

    @pytest.mark.asyncio
    async def test_start_creates_session(self, tracker, mock_bot):
        """After start(), the session is stored and marked active."""
        await tracker.start(
            bot=mock_bot,
            trip_id=1,
            chat_id=12345,
            lat=48.1351,
            lon=11.5820,
        )

        session = tracker.get_session(1)
        assert session is not None
        assert session.chat_id == 12345
        assert session.message_id == 42
        assert session.trip_id == 1
        assert session.is_active is True
        assert session.last_lat == 48.1351
        assert session.last_lon == 11.5820

    @pytest.mark.asyncio
    async def test_start_with_custom_live_period(self, tracker, mock_bot):
        """Custom live_period is passed to send_location."""
        await tracker.start(
            bot=mock_bot,
            trip_id=2,
            chat_id=12345,
            lat=48.0,
            lon=11.0,
            live_period=1800,
        )

        mock_bot.send_location.assert_called_once_with(
            chat_id=12345,
            latitude=48.0,
            longitude=11.0,
            live_period=1800,
        )

    @pytest.mark.asyncio
    async def test_start_invalid_coordinates_returns_none(self, tracker, mock_bot):
        """Invalid coordinates return None without calling the bot."""
        result = await tracker.start(
            bot=mock_bot,
            trip_id=1,
            chat_id=12345,
            lat=200.0,
            lon=0.0,
        )

        assert result is None
        mock_bot.send_location.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_user_blocked_bot_returns_none(self, tracker, mock_bot):
        """When patient blocks the bot, start returns None and logs warning."""
        mock_bot.send_location.side_effect = Forbidden("bot was blocked")

        result = await tracker.start(
            bot=mock_bot,
            trip_id=1,
            chat_id=12345,
            lat=48.0,
            lon=11.0,
        )

        assert result is None
        assert tracker.is_tracking(1) is False

    @pytest.mark.asyncio
    async def test_start_telegram_error_returns_none(self, tracker, mock_bot):
        """General Telegram errors are caught and return None."""
        from telegram.error import NetworkError
        mock_bot.send_location.side_effect = NetworkError("timeout")

        result = await tracker.start(
            bot=mock_bot,
            trip_id=1,
            chat_id=12345,
            lat=48.0,
            lon=11.0,
        )

        assert result is None
        assert tracker.is_tracking(1) is False


# ═══════════════════════════════════════════════════════════════════════════
# Update live location tests
# ═══════════════════════════════════════════════════════════════════════════


class TestUpdateLiveLocation:
    """LiveLocationTracker.update() tests."""

    @pytest.mark.asyncio
    async def test_update_edits_existing_message(self, tracker, mock_bot):
        """update() calls edit_message_live_location with correct params."""
        # Start first
        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=12345,
            lat=48.1351, lon=11.5820,
        )

        # Move the driver
        result = await tracker.update(
            bot=mock_bot, trip_id=1,
            lat=48.1400, lon=11.5900,
        )

        assert result is True
        mock_bot.edit_message_live_location.assert_called_once_with(
            chat_id=12345,
            message_id=42,
            latitude=48.1400,
            longitude=11.5900,
        )

    @pytest.mark.asyncio
    async def test_update_updates_last_position(self, tracker, mock_bot):
        """After update(), session.last_lat/lon reflect the new position."""
        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=12345,
            lat=48.0, lon=11.0,
        )
        await tracker.update(
            bot=mock_bot, trip_id=1,
            lat=49.0, lon=12.0,
        )

        session = tracker.get_session(1)
        assert session.last_lat == 49.0
        assert session.last_lon == 12.0

    @pytest.mark.asyncio
    async def test_update_no_session_returns_false(self, tracker, mock_bot):
        """update() on non-existent trip returns False."""
        result = await tracker.update(
            bot=mock_bot, trip_id=999,
            lat=48.0, lon=11.0,
        )

        assert result is False
        mock_bot.edit_message_live_location.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_inactive_session_returns_false(self, tracker, mock_bot):
        """update() on a stopped session returns False."""
        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=12345,
            lat=48.0, lon=11.0,
        )
        tracker.get_session(1).is_active = False

        result = await tracker.update(
            bot=mock_bot, trip_id=1,
            lat=49.0, lon=12.0,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_update_invalid_coordinates_returns_false(self, tracker, mock_bot):
        """update() with invalid coordinates returns False."""
        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=12345,
            lat=48.0, lon=11.0,
        )

        result = await tracker.update(
            bot=mock_bot, trip_id=1,
            lat=200.0, lon=11.0,
        )

        assert result is False
        mock_bot.edit_message_live_location.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_message_not_found_marks_inactive(self, tracker, mock_bot):
        """BadRequest (message deleted/expired) marks session inactive."""
        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=12345,
            lat=48.0, lon=11.0,
        )
        mock_bot.edit_message_live_location.side_effect = BadRequest(
            "message to edit not found"
        )

        result = await tracker.update(
            bot=mock_bot, trip_id=1,
            lat=49.0, lon=12.0,
        )

        assert result is False
        assert tracker.is_tracking(1) is False


# ═══════════════════════════════════════════════════════════════════════════
# Stop live location tests
# ═══════════════════════════════════════════════════════════════════════════


class TestStopLiveLocation:
    """LiveLocationTracker.stop() tests."""

    @pytest.mark.asyncio
    async def test_stop_calls_stop_message_live_location(self, tracker, mock_bot):
        """stop() calls the Telegram API to end live location sharing."""
        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=12345,
            lat=48.0, lon=11.0,
        )

        result = await tracker.stop(bot=mock_bot, trip_id=1)

        assert result is True
        mock_bot.stop_message_live_location.assert_called_once_with(
            chat_id=12345,
            message_id=42,
        )

    @pytest.mark.asyncio
    async def test_stop_removes_session(self, tracker, mock_bot):
        """After stop(), the session is removed from the tracker."""
        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=12345,
            lat=48.0, lon=11.0,
        )

        await tracker.stop(bot=mock_bot, trip_id=1)

        assert tracker.get_session(1) is None
        assert tracker.is_tracking(1) is False

    @pytest.mark.asyncio
    async def test_stop_nonexistent_trip_is_idempotent(self, tracker, mock_bot):
        """stop() on a non-existent trip returns True (idempotent)."""
        result = await tracker.stop(bot=mock_bot, trip_id=999)

        assert result is True
        mock_bot.stop_message_live_location.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_inactive_session(self, tracker, mock_bot):
        """stop() on an already-inactive session still works."""
        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=12345,
            lat=48.0, lon=11.0,
        )
        tracker.get_session(1).is_active = False

        result = await tracker.stop(bot=mock_bot, trip_id=1)

        assert result is True

    @pytest.mark.asyncio
    async def test_stop_bad_request_handled_gracefully(self, tracker, mock_bot):
        """BadRequest on stop is handled without exception."""
        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=12345,
            lat=48.0, lon=11.0,
        )
        mock_bot.stop_message_live_location.side_effect = BadRequest(
            "message already deleted"
        )

        result = await tracker.stop(bot=mock_bot, trip_id=1)

        assert result is True
        assert tracker.get_session(1) is None


# ═══════════════════════════════════════════════════════════════════════════
# Session tracking queries
# ═══════════════════════════════════════════════════════════════════════════


class TestSessionTracking:
    """LiveLocationTracker query methods."""

    @pytest.mark.asyncio
    async def test_is_tracking_new_tracker(self, tracker):
        """A new tracker has no active sessions."""
        assert tracker.is_tracking(1) is False

    @pytest.mark.asyncio
    async def test_is_tracking_after_start(self, tracker, mock_bot):
        """is_tracking returns True after start()."""
        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=12345,
            lat=48.0, lon=11.0,
        )
        assert tracker.is_tracking(1) is True

    @pytest.mark.asyncio
    async def test_is_tracking_after_stop(self, tracker, mock_bot):
        """is_tracking returns False after stop()."""
        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=12345,
            lat=48.0, lon=11.0,
        )
        await tracker.stop(bot=mock_bot, trip_id=1)
        assert tracker.is_tracking(1) is False

    @pytest.mark.asyncio
    async def test_active_count(self, tracker, mock_bot):
        """active_count reports the number of active sessions."""
        assert tracker.active_count == 0

        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=12345,
            lat=48.0, lon=11.0,
        )
        assert tracker.active_count == 1

        await tracker.start(
            bot=mock_bot, trip_id=2, chat_id=12346,
            lat=49.0, lon=12.0,
        )
        assert tracker.active_count == 2

        await tracker.stop(bot=mock_bot, trip_id=1)
        assert tracker.active_count == 1

    @pytest.mark.asyncio
    async def test_get_session_nonexistent(self, tracker):
        """get_session returns None for unknown trips."""
        assert tracker.get_session(999) is None


# ═══════════════════════════════════════════════════════════════════════════
# Full lifecycle integration test
# ═══════════════════════════════════════════════════════════════════════════


class TestFullLifecycle:
    """End-to-end: start → update (multiple) → stop."""

    @pytest.mark.asyncio
    async def test_full_driver_journey(self, tracker, mock_bot):
        """Simulate a driver going from base → pickup → destination."""
        # Start at driver's base
        await tracker.start(
            bot=mock_bot, trip_id=100, chat_id=999,
            lat=48.10, lon=11.50, live_period=600,
        )
        assert tracker.is_tracking(100) is True
        assert tracker.active_count == 1

        # Driver moves toward pickup — three updates
        positions = [
            (48.11, 11.52),
            (48.12, 11.54),
            (48.13, 11.56),  # Arrived
        ]
        for lat, lon in positions:
            ok = await tracker.update(bot=mock_bot, trip_id=100, lat=lat, lon=lon)
            assert ok is True

        session = tracker.get_session(100)
        assert session.last_lat == 48.13
        assert session.last_lon == 11.56

        # End of journey
        await tracker.stop(bot=mock_bot, trip_id=100)
        assert tracker.is_tracking(100) is False
        assert tracker.active_count == 0

    @pytest.mark.asyncio
    async def test_multiple_concurrent_sessions(self, tracker, mock_bot):
        """Track two trips simultaneously from different chats."""
        # Trip A: chat 100
        await tracker.start(
            bot=mock_bot, trip_id=1, chat_id=100,
            lat=48.0, lon=11.0,
        )

        # Trip B: chat 200 (different send_location mock result)
        send_result_b = MagicMock()
        send_result_b.message_id = 99
        mock_bot.send_location.return_value = send_result_b
        await tracker.start(
            bot=mock_bot, trip_id=2, chat_id=200,
            lat=49.0, lon=12.0,
        )

        assert tracker.active_count == 2

        # Update only trip A
        await tracker.update(bot=mock_bot, trip_id=1, lat=48.1, lon=11.1)
        assert tracker.get_session(1).last_lat == 48.1

        # Trip B was not affected
        assert tracker.get_session(2).last_lat == 49.0

        # Stop only trip A
        await tracker.stop(bot=mock_bot, trip_id=1)
        assert tracker.is_tracking(1) is False
        assert tracker.is_tracking(2) is True
        assert tracker.active_count == 1


# ═══════════════════════════════════════════════════════════════════════════
# Patient-bot state decision functions
# ═══════════════════════════════════════════════════════════════════════════


class TestPatientBotStateDecisions:
    """Tests for should_start/stop_live_location and should_notify_patient.

    Sets required env vars before import because patient_bot.py imports
    krankenfahrt.config which reads env vars at module level.
    """

    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        """Ensure required env vars are set before importing patient_bot."""
        monkeypatch.setenv("PATIENT_BOT_TOKEN", "test_patient_token")
        monkeypatch.setenv("DRIVER_BOT_TOKEN", "test_driver_token")
        monkeypatch.setenv("CHEF_BOT_TOKEN", "test_chef_token")
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test_deepseek_key")

    def test_start_live_location_on_anfahrt(self):
        from krankenfahrt.bots.patient_bot import should_start_live_location
        assert should_start_live_location("anfahrt") is True

    def test_no_start_on_other_states(self):
        from krankenfahrt.bots.patient_bot import should_start_live_location
        for state in ("geplant", "zugewiesen", "angekommen", "abgeschlossen"):
            assert should_start_live_location(state) is False, f"state={state}"

    def test_stop_live_location_on_terminal_states(self):
        from krankenfahrt.bots.patient_bot import should_stop_live_location
        for state in ("angekommen", "abgesetzt", "abgeschlossen", "storniert"):
            assert should_stop_live_location(state) is True, f"state={state}"

    def test_no_stop_on_transit_states(self):
        from krankenfahrt.bots.patient_bot import should_stop_live_location
        for state in ("geplant", "zugewiesen", "anfahrt", "patient_an_bord", "unterwegs"):
            assert should_stop_live_location(state) is False, f"state={state}"

    def test_notify_on_all_transitions(self):
        from krankenfahrt.bots.patient_bot import should_notify_patient
        notifiable = {
            "zugewiesen", "anfahrt", "angekommen", "patient_an_bord",
            "unterwegs", "abgesetzt", "abgeschlossen", "storniert", "problem",
        }
        for state in notifiable:
            assert should_notify_patient(state) is True, f"state={state}"

    def test_no_notify_on_geplant(self):
        from krankenfahrt.bots.patient_bot import should_notify_patient
        # "geplant" is the initial state — patient already knows from booking
        # confirmation, so we don't send a separate notification.
        assert should_notify_patient("geplant") is False
