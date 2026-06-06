"""Morning-Push service — sends daily shift overview to drivers at 06:00.

The push runs:
  1. Once at startup (to catch any missed push)
  2. Daily at 06:00 local time thereafter

For each driver with trips scheduled today, it sends a personalised
overview via Telegram.
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from telegram.ext import Application

from krankenfahrt.models.schema import Driver, Trip

logger = logging.getLogger(__name__)

# Set of driver IDs that already received their morning push today.
# Resets when the date changes.
_pushed_today: dict[date, set[int]] = {}


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


async def send_morning_push(app: Application) -> int:
    """Send the morning overview to all drivers who have trips today.

    Skips drivers who already received the push today.
    Returns the number of drivers notified.
    """
    today = date.today()

    # Reset push tracking if date changed
    if today not in _pushed_today:
        _pushed_today.clear()
        _pushed_today[today] = set()

    already_pushed = _pushed_today[today]

    # Find all trips scheduled for today
    day_start = datetime(today.year, today.month, today.day)
    day_end = day_start + timedelta(days=1)

    trips_today = await Trip.filter(
        scheduled_pickup__gte=day_start,
        scheduled_pickup__lt=day_end,
    ).prefetch_related("driver", "patient").order_by("scheduled_pickup")

    # Group trips by driver
    driver_trips: dict[int, dict] = {}
    for trip in trips_today:
        if trip.driver_id is None:
            continue
        did = trip.driver_id
        if did in already_pushed:
            continue
        if did not in driver_trips:
            driver_trips[did] = {
                "driver": None,
                "trips": [],
            }
        driver_trips[did]["trips"].append(trip)

    if not driver_trips:
        logger.info("Morning-Push: No drivers with unsent trips today")
        return 0

    # Resolve driver objects
    driver_ids = list(driver_trips.keys())
    drivers = await Driver.filter(id__in=driver_ids)
    driver_map = {d.id: d for d in drivers}

    notified = 0
    for did, data in driver_trips.items():
        driver = driver_map.get(did)
        if driver is None or driver.telegram_id is None or driver.telegram_id <= 0:
            continue

        trips = data["trips"]

        # Build morning message
        first_pickup = min(t.scheduled_pickup for t in trips)
        last_dropoff = max(
            (t.scheduled_dropoff or t.scheduled_pickup) for t in trips
        )

        lines = [
            f"🌅 *Guten Morgen, {driver.name}!*",
            "",
            f"📅 Deine Schicht heute: {_fmt_time(first_pickup)} – {_fmt_time(last_dropoff)}",
            f"🚗 Fahrten: *{len(trips)}*",
            "",
            "📋 *Deine Fahrten:*",
        ]

        status_emoji = {
            "geplant": "⏳",
            "zugewiesen": "📋",
            "anfahrt": "🚗",
            "angekommen": "📍",
            "patient_an_bord": "👤",
            "unterwegs": "🏥",
            "abgesetzt": "✅",
            "abgeschlossen": "✔️",
            "storniert": "❌",
            "problem": "⚠️",
        }

        for t in trips:
            emoji = status_emoji.get(t.status, "❓")
            pickup = _fmt_time(t.scheduled_pickup)
            dropoff = _fmt_time(t.scheduled_dropoff) if t.scheduled_dropoff else "??:??"
            dest_short = t.dest_addr[:35] + "…" if len(t.dest_addr) > 35 else t.dest_addr
            lines.append(f"{emoji} `{pickup}–{dropoff}` → {dest_short}")

        lines.append("")
        lines.append("💪 Einen guten Start in die Schicht!")
        lines.append("_/heute für Details, /pause für Pausen_")

        try:
            await app.bot.send_message(
                chat_id=driver.telegram_id,
                text="\n".join(lines),
                parse_mode="Markdown",
            )
            already_pushed.add(did)
            notified += 1
            logger.info("Morning-Push sent to driver %s (id=%d)", driver.name, did)
        except Exception as exc:
            logger.error(
                "Morning-Push failed for driver %s (id=%d, tg=%d): %s",
                driver.name, did, driver.telegram_id, exc,
            )

    logger.info("Morning-Push: %d drivers notified", notified)
    return notified


async def _seconds_until_next(hour: int, minute: int) -> float:
    """Calculate seconds until the next occurrence of HH:MM local time."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_morning_push_loop(app: Application) -> None:
    """Main loop: send push at startup, then daily at 06:00.

    Runs forever — should be started as an asyncio background task.
    """
    logger.info("Morning-Push: Running initial push...")
    try:
        await send_morning_push(app)
    except Exception:
        logger.exception("Morning-Push: Initial push failed")

    while True:
        delay = await _seconds_until_next(6, 0)  # 06:00
        logger.info("Morning-Push: Next push in %.0f seconds (at 06:00)", delay)
        await asyncio.sleep(delay)

        try:
            await send_morning_push(app)
        except Exception:
            logger.exception("Morning-Push: Scheduled push failed")
