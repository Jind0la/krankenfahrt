"""Driver-Bot (@FahrLenker): Driver's daily shift companion.

Commands:
  /heute  — Today's trip overview, shift status, remaining break time
  /pause  — Toggle break (start/end) — records break time
  /start  — Welcome message with available commands
"""

import logging
from datetime import date, datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from krankenfahrt.models.schema import Driver, DriverBreak, Trip

logger = logging.getLogger(__name__)


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────


async def _get_driver(telegram_id: int) -> Driver | None:
    """Look up a driver by Telegram ID. Returns None if not found."""
    return await Driver.filter(telegram_id=telegram_id).first()


async def _get_todays_trips(driver: Driver) -> list[Trip]:
    """All trips assigned to this driver with scheduled_pickup today."""
    today = date.today()
    return await Trip.filter(
        driver_id=driver.id,
        scheduled_pickup__gte=datetime(today.year, today.month, today.day),
        scheduled_pickup__lt=datetime(today.year, today.month, today.day + 1),
    ).order_by("scheduled_pickup")


async def _get_active_break(driver: Driver) -> DriverBreak | None:
    """Find the driver's currently active (unfinished) break, if any."""
    return await DriverBreak.filter(
        driver_id=driver.id, end_time__isnull=True
    ).first()


async def _get_todays_breaks(driver: Driver) -> list[DriverBreak]:
    """All breaks this driver took today."""
    today = date.today()
    return await DriverBreak.filter(
        driver_id=driver.id,
        start_time__gte=datetime(today.year, today.month, today.day),
        start_time__lt=datetime(today.year, today.month, today.day + 1),
    ).order_by("start_time")


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _fmt_date(d: date) -> str:
    months = [
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ]
    return f"{d.day}. {months[d.month - 1]} {d.year}"


# ── /start ───────────────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message with available commands."""
    await update.message.reply_text(
        "🚑 *FahrLenker* — Dein Fahrer-Assistent\n\n"
        "Verfügbare Befehle:\n"
        "/heute — Tagesübersicht mit allen Fahrten\n"
        "/pause — Pause starten / beenden\n\n"
        "_Bei Fragen wende dich an deinen Disponenten._",
        parse_mode="Markdown",
    )


# ── /heute ───────────────────────────────────────────────────────────────────


async def cmd_heute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Today's trip overview for the driver.

    Shows:
      - All scheduled trips today with status and times
      - Active shift info (first pickup → last dropoff)
      - Break summary (completed + active break)
    """
    tg_id = update.effective_user.id
    driver = await _get_driver(tg_id)

    if driver is None:
        await update.message.reply_text(
            "❌ Du bist nicht als Fahrer registriert. "
            "Bitte wende dich an deinen Disponenten."
        )
        return

    trips = await _get_todays_trips(driver)
    breaks = await _get_todays_breaks(driver)
    active_break = await _get_active_break(driver)

    today = date.today()

    # Build response
    lines = [f"📅 *Tagesübersicht – {_fmt_date(today)}*", ""]

    # ── Shift info ──
    if trips:
        lines.append(f"👤 Fahrer: *{driver.name}*")
        lines.append(f"🚗 Fahrten heute: *{len(trips)}*")
        lines.append("")

        # Shift window
        first_pickup = min(t.scheduled_pickup for t in trips)
        last_dropoff = max(
            (t.scheduled_dropoff or t.scheduled_pickup) for t in trips
        )
        lines.append(
            f"⏰ Schicht: {_fmt_time(first_pickup)} – {_fmt_time(last_dropoff)}"
        )
        lines.append("")

        # ── Trip list ──
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
            dest_short = t.dest_addr[:30] + "…" if len(t.dest_addr) > 30 else t.dest_addr
            lines.append(f"{emoji} `{pickup}–{dropoff}` → {dest_short}")
            if t.patient_id:
                lines.append(f"   _{t.status}_")

        lines.append("")
    else:
        lines.append("✅ Heute *keine Fahrten* geplant. Genieß den freien Tag! ☀️")

    # ── Break info ──
    if breaks:
        total_break_minutes = 0
        lines.append("☕ *Pausen:*")
        for b in breaks:
            b_start = _fmt_time(b.start_time)
            if b.end_time:
                duration = (b.end_time - b.start_time).total_seconds() / 60
                total_break_minutes += duration
                lines.append(f"  • {b_start} – {_fmt_time(b.end_time)} ({int(duration)} Min.)")
            else:
                lines.append(f"  • {b_start} – *läuft...* ⏳")
        if total_break_minutes > 0 and not active_break:
            lines.append(f"  _Gesamt: {int(total_break_minutes)} Minuten_")

    if active_break:
        lines.append("")
        lines.append("🟡 *Pause aktiv* — /pause zum Beenden")

    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown"
    )


# ── /pause ───────────────────────────────────────────────────────────────────


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle break: start a new break or end the current one.

    - If no active break → starts a break (records start_time)
    - If break active → ends it (records end_time, computes duration)
    """
    tg_id = update.effective_user.id
    driver = await _get_driver(tg_id)

    if driver is None:
        await update.message.reply_text(
            "❌ Du bist nicht als Fahrer registriert."
        )
        return

    active_break = await _get_active_break(driver)

    if active_break is None:
        # ── START BREAK ──
        new_break = await DriverBreak.create(
            driver=driver, start_time=datetime.now()
        )
        logger.info(
            "Driver %s (id=%d) started break at %s",
            driver.name, driver.id, new_break.start_time,
        )
        await update.message.reply_text(
            f"☕ *Pause gestartet* um {_fmt_time(new_break.start_time)} Uhr.\n"
            "Viel Erholung! Mit /pause beendest du die Pause.",
            parse_mode="Markdown",
        )
    else:
        # ── END BREAK ──
        now = datetime.now()
        active_break.end_time = now
        await active_break.save()

        duration_min = int((now - active_break.start_time).total_seconds() / 60)
        logger.info(
            "Driver %s (id=%d) ended break — duration: %d min",
            driver.name, driver.id, duration_min,
        )
        await update.message.reply_text(
            f"✅ *Pause beendet* um {_fmt_time(now)} Uhr.\n"
            f"⏱ Dauer: *{duration_min} Minuten*",
            parse_mode="Markdown",
        )


# ── Handler-Registrierung ────────────────────────────────────────────────────


def register_handlers(app: Application) -> None:
    """Register all driver bot command handlers."""
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("heute", cmd_heute))
    app.add_handler(CommandHandler("pause", cmd_pause))
    logger.info("Driver-Bot handlers registered: start, heute, pause")
