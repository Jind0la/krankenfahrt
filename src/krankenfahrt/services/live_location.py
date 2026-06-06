"""Live Location Tracking Service.

Manages Telegram live location sharing sessions for patient transport tracking.
Uses edit_message_live_location to update an existing location message rather
than sending new messages on each position change — the Telegram UI shows a
moving blue dot for a cohesive tracking experience.

Lifecycle per trip:
  1. start()  — sends initial location via send_location(live_period=N)
  2. update() — edits the same message via edit_message_live_location
  3. stop()   — stops sharing via stop_message_live_location

Sessions are tracked in-memory keyed by trip_id. In production, this would be
persisted to survive restarts; that's out of scope for the MVP.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from telegram import Bot
from telegram.error import BadRequest, Forbidden, TelegramError

logger = logging.getLogger(__name__)


@dataclass
class LiveLocationSession:
    """A single live-tracking session for one trip."""

    chat_id: int
    message_id: int
    trip_id: int
    is_active: bool = True
    last_lat: float = 0.0
    last_lon: float = 0.0


class LiveLocationTracker:
    """Manages live location sharing sessions for the patient Telegram bot.

    The tracker stores the (chat_id, message_id) tuple for each active session
    so subsequent position updates can call edit_message_live_location on the
    correct message instead of sending a new one.
    """

    # Default live period in seconds (1 hour). Telegram auto-terminates live
    # location after this period unless stop() is called first.
    DEFAULT_LIVE_PERIOD = 3600

    def __init__(self) -> None:
        self._sessions: dict[int, LiveLocationSession] = {}  # trip_id → session

    # ── Public API ──────────────────────────────────────────────────────────

    async def start(
        self,
        bot: Bot,
        trip_id: int,
        chat_id: int,
        lat: float,
        lon: float,
        live_period: int = DEFAULT_LIVE_PERIOD,
    ) -> Optional[int]:
        """Start live location sharing for a trip.

        Sends an initial location message with live_period set. Stores the
        returned message_id so subsequent update() calls can edit it.

        Args:
            bot: The Telegram Bot instance for this patient bot.
            trip_id: The database trip ID used as the session key.
            chat_id: Telegram chat ID of the patient.
            lat, lon: Initial driver position.
            live_period: How long the live location stays active (seconds).

        Returns:
            The message_id of the sent location message, or None on failure.
        """
        if not self._validate_coordinates(lat, lon):
            logger.warning(
                "Invalid coordinates for trip %d: lat=%.6f lon=%.6f",
                trip_id, lat, lon,
            )
            return None

        try:
            message = await bot.send_location(
                chat_id=chat_id,
                latitude=lat,
                longitude=lon,
                live_period=live_period,
            )
        except Forbidden:
            logger.warning("Patient %d blocked the bot; cannot send location", chat_id)
            return None
        except TelegramError as e:
            logger.error("Failed to start live location for trip %d: %s", trip_id, e)
            return None

        self._sessions[trip_id] = LiveLocationSession(
            chat_id=chat_id,
            message_id=message.message_id,
            trip_id=trip_id,
            is_active=True,
            last_lat=lat,
            last_lon=lon,
        )

        logger.info(
            "Live location started: trip=%d chat=%d msg=%d",
            trip_id, chat_id, message.message_id,
        )
        return message.message_id

    async def update(
        self,
        bot: Bot,
        trip_id: int,
        lat: float,
        lon: float,
    ) -> bool:
        """Update the live location for an active session.

        Edits the existing location message instead of sending a new one.
        The Telegram UI reflects this as the blue dot moving.

        Args:
            bot: Telegram Bot instance.
            trip_id: Trip ID whose location to update.
            lat, lon: New driver position.

        Returns:
            True if the update was sent successfully.
        """
        session = self._sessions.get(trip_id)
        if session is None:
            logger.warning("No live location session for trip %d", trip_id)
            return False

        if not session.is_active:
            logger.warning("Live location session for trip %d is not active", trip_id)
            return False

        if not self._validate_coordinates(lat, lon):
            logger.warning(
                "Invalid coordinates for trip %d update: lat=%.6f lon=%.6f",
                trip_id, lat, lon,
            )
            return False

        try:
            await bot.edit_message_live_location(
                chat_id=session.chat_id,
                message_id=session.message_id,
                latitude=lat,
                longitude=lon,
            )
        except BadRequest as e:
            # BadRequest can mean the message was deleted or the live period
            # expired and the message can no longer be edited.
            logger.warning(
                "Cannot update live location for trip %d: %s — marking inactive",
                trip_id, e,
            )
            session.is_active = False
            return False
        except TelegramError as e:
            logger.error(
                "Failed to update live location for trip %d: %s", trip_id, e,
            )
            return False

        session.last_lat = lat
        session.last_lon = lon
        logger.debug(
            "Live location updated: trip=%d lat=%.6f lon=%.6f",
            trip_id, lat, lon,
        )
        return True

    async def stop(self, bot: Bot, trip_id: int) -> bool:
        """Stop live location sharing for a trip.

        After this call the Telegram UI stops showing the live location.

        Args:
            bot: Telegram Bot instance.
            trip_id: Trip ID whose sharing to stop.

        Returns:
            True if location was successfully stopped or already inactive.
        """
        session = self._sessions.pop(trip_id, None)
        if session is None:
            logger.debug("No session found for trip %d to stop", trip_id)
            return True  # Nothing to stop — idempotent

        if not session.is_active:
            return True

        try:
            await bot.stop_message_live_location(
                chat_id=session.chat_id,
                message_id=session.message_id,
            )
        except BadRequest as e:
            # Message may already be deleted or live period expired.
            logger.info(
                "Live location for trip %d already stopped or expired: %s",
                trip_id, e,
            )
        except TelegramError as e:
            logger.error(
                "Failed to stop live location for trip %d: %s", trip_id, e,
            )
            # Still mark as stopped even if the API call fails — we don't want
            # to keep a dead session around.
        finally:
            session.is_active = False

        logger.info("Live location stopped for trip %d", trip_id)
        return True

    # ── Query helpers ───────────────────────────────────────────────────────

    def get_session(self, trip_id: int) -> Optional[LiveLocationSession]:
        """Return the live location session for a trip, if any."""
        return self._sessions.get(trip_id)

    def is_tracking(self, trip_id: int) -> bool:
        """Check whether live location is active for a trip."""
        session = self._sessions.get(trip_id)
        return session is not None and session.is_active

    @property
    def active_count(self) -> int:
        """Number of currently active live location sessions."""
        return sum(1 for s in self._sessions.values() if s.is_active)

    # ── Internal helpers ────────────────────────────────────────────────────

    @staticmethod
    def _validate_coordinates(lat: float, lon: float) -> bool:
        """Validate latitude/longitude are within Earth bounds."""
        return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0
