"""Driver-Bot (@FahrLenker): Order acceptance, status updates, and shift management.

State machine integration: all transitions enforced by TripStateMachine.
Only valid next-state buttons are shown per TRIGGER_MAP from state_machine.py.

Flow:
  1. Driver receives order notification with inline keyboard.
  2. Driver presses "Annehmen" (accept) → triggers "losfahren" → "anfahrt".
  3. Message updates to show new state + new keyboard.
  4. Driver advances through: Angekommen → Abgeholt → Zugestellt → Abschließen.

Commands:
  /heute  — Today's trip overview with shift status and break info
  /pause  — Toggle break start/end during shift
  /start  — Register driver or show status
"""

from datetime import UTC, date, datetime

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
    MessageHandler, filters,
)
from tortoise.exceptions import DoesNotExist

from krankenfahrt.core.state_machine import TRIGGER_MAP, TripStateMachine
from krankenfahrt.models.schema import Driver, DriverBreak, Trip, TripEvent
from krankenfahrt.services.driver_intent import extract_driver_intent
from krankenfahrt.services.voice import transcribe_voice

logger = structlog.get_logger(__name__)


def _now() -> datetime:
    """Return current datetime with UTC timezone, matching Tortoise's aware storage."""
    return datetime.now(UTC)

# ── Callback data format ──────────────────────────────────────────────
# "trip:{trip_id}:{trigger_name}"  e.g. "trip:42:losfahren"
CALLBACK_PREFIX = "trip"


def _pack_callback(trip_id: int, trigger: str) -> str:
    """Encode trip id and trigger name into callback data string."""
    return f"{CALLBACK_PREFIX}:{trip_id}:{trigger}"


def _unpack_callback(data: str) -> tuple[int, str] | None:
    """Decode callback data into (trip_id, trigger). Returns None if malformed."""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        return None
    try:
        return int(parts[1]), parts[2]
    except ValueError:
        return None


# ── Button label mapping ──────────────────────────────────────────────
# Driver-friendly labels for each state machine trigger.
# "Annehmen" / "Abgeholt" / "Zugestellt" are the primary buttons per the task spec.
DRIVER_BUTTON_LABELS: dict[str, str] = {
    "losfahren": "✅ Annehmen",
    "stornieren": "❌ Ablehnen",
    "ankunft_melden": "📍 Angekommen",
    "patient_aufnehmen": "👤 Abgeholt",
    "fahrt_beginnen": "🚗 Fahrt beginnt",
    "patient_absetzen": "✅ Zugestellt",
    "abschliessen": "🔒 Abschließen",
    "problem_melden": "⚠️ Problem",
    "fahrer_neu_zuweisen": "🔄 Neu zuweisen",
}

# ── State display names ───────────────────────────────────────────────
STATE_DISPLAY: dict[str, str] = {
    "geplant": "🆕 Geplant",
    "zugewiesen": "📋 Zugewiesen",
    "anfahrt": "🚗 Anfahrt",
    "angekommen": "📍 Angekommen",
    "patient_an_bord": "👤 Patient an Bord",
    "unterwegs": "🏥 Unterwegs",
    "abgesetzt": "✅ Abgesetzt",
    "abgeschlossen": "🔒 Abgeschlossen",
    "storniert": "❌ Storniert",
    "problem": "⚠️ Problem",
}


# ── Keyboard builder ──────────────────────────────────────────────────

def build_trip_keyboard(status: str) -> InlineKeyboardMarkup | None:
    """Build an inline keyboard with only the valid next-state buttons.

    Returns None if no valid transitions exist (terminal states).
    """
    triggers = TRIGGER_MAP.get(status, [])
    if not triggers:
        return None

    buttons: list[list[InlineKeyboardButton]] = []
    for trigger in triggers:
        label = DRIVER_BUTTON_LABELS.get(trigger, trigger)
        # Primary action buttons get their own row; problem/storno on separate rows
        buttons.append(
            [InlineKeyboardButton(label, callback_data=_pack_callback(0, trigger))]
        )

    return InlineKeyboardMarkup(buttons)


def build_trip_keyboard_for_trip(trip_id: int, status: str) -> InlineKeyboardMarkup | None:
    """Build keyboard with trip_id baked into callback data."""
    triggers = TRIGGER_MAP.get(status, [])
    if not triggers:
        return None

    buttons: list[list[InlineKeyboardButton]] = []
    for trigger in triggers:
        label = DRIVER_BUTTON_LABELS.get(trigger, trigger)
        buttons.append(
            [InlineKeyboardButton(label, callback_data=_pack_callback(trip_id, trigger))]
        )

    return InlineKeyboardMarkup(buttons)


# ── Trip info formatter ───────────────────────────────────────────────

def format_trip_info(trip: Trip, patient_name: str, vehicle_type: str) -> str:
    """Format a trip summary message for the driver."""
    pickup_time = trip.scheduled_pickup.strftime("%d.%m.%Y %H:%M") if trip.scheduled_pickup else "?"
    status_display = STATE_DISPLAY.get(trip.status, trip.status)

    lines = [
        f"📋 **Fahrt #{trip.id}** — {status_display}",
        "",
        f"👤 Patient: {patient_name}",
        f"⏰ Abholung: {pickup_time}",
        f"📍 Von: {trip.pickup_addr}",
        f"🏥 Nach: {trip.dest_addr}",
        f"🚗 Typ: {vehicle_type}",
    ]

    if trip.scheduled_dropoff:
        dropoff = trip.scheduled_dropoff.strftime("%H:%M")
        lines.append(f"⏱ Geplante Ankunft: {dropoff}")

    # Navigation link (Google Maps directions from pickup to destination)
    nav_link = (
        f"https://www.google.com/maps/dir/"
        f"{trip.pickup_addr}/{trip.dest_addr}"
    )
    lines.append(f"\n[🗺 Navigation]({nav_link})")

    return "\n".join(lines)


# ── Command handlers ──────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — Register driver or show status."""
    telegram_id = update.effective_user.id if update.effective_user else 0

    try:
        driver = await Driver.get(telegram_id=telegram_id)
        await update.message.reply_text(
            f"🚑 Willkommen zurück, {driver.name}!\n\n"
            "Neue Aufträge erscheinen hier mit Aktions-Buttons.\n\n"
            "Befehle:\n"
            "/heute — heutige Fahrten\n"
            "/fertig — Schicht beenden",
        )
    except DoesNotExist:
        await update.message.reply_text(
            f"❌ Du bist nicht als Fahrer registriert.\n"
            f"Deine Telegram-ID: `{telegram_id}`\n\n"
            f"Bitte gib diese ID deinem Disponenten. "
            f"Er kann dich mit `/fahrer add <Name> <Telefon> {telegram_id}` registrieren."
        )


# ── Schicht-Hilfsfunktionen ─────────────────────────────────────────────


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
    """All breaks relevant to today's shift — includes:
    - Breaks that started today
    - Breaks that started yesterday but are still active (span midnight)
    - Breaks that started yesterday and ended today (completed across midnight)
    """
    today = date.today()
    today_start = datetime(today.year, today.month, today.day)
    tomorrow_start = datetime(today.year, today.month, today.day + 1)

    from tortoise.expressions import Q

    return await DriverBreak.filter(
        driver_id=driver.id,
    ).filter(
        Q(start_time__gte=today_start, start_time__lt=tomorrow_start)
        | Q(end_time__gte=today_start, end_time__lt=tomorrow_start)
        | Q(start_time__lt=today_start, end_time__isnull=True)
    ).order_by("start_time")


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _fmt_date(d: date) -> str:
    months = [
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ]
    return f"{d.day}. {months[d.month - 1]} {d.year}"


# ── /heute ───────────────────────────────────────────────────────────────


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


# ── /pause ───────────────────────────────────────────────────────────────


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
            driver=driver, start_time=_now()
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
        now = _now()
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


# ── Callback query handler ────────────────────────────────────────────

async def handle_trip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses for trip state transitions.

    Flow:
      1. Decode callback data → trip_id + trigger.
      2. Load trip and verify the pressing driver is assigned.
      3. Run the state machine transition.
      4. Persist to DB, log event.
      5. Update the message with new state + keyboard.
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the button press immediately

    # Decode callback data
    data = query.data
    unpacked = _unpack_callback(data)
    if unpacked is None:
        logger.warning("Malformed callback data", data=data)
        await query.edit_message_text("❌ Ungültige Aktion.")
        return

    trip_id, trigger = unpacked
    telegram_id = update.effective_user.id if update.effective_user else 0

    # Load trip with related data
    try:
        trip = await Trip.get(id=trip_id).prefetch_related("patient", "driver")
    except DoesNotExist:
        logger.warning("Trip not found for callback", trip_id=trip_id)
        await query.edit_message_text("❌ Fahrt nicht gefunden.")
        return

    # Verify this driver is assigned to this trip
    driver = await trip.driver
    if driver is None or driver.telegram_id != telegram_id:
        logger.warning(
            "Unauthorized callback",
            trip_id=trip_id,
            telegram_id=telegram_id,
            assigned_driver_id=driver.telegram_id if driver else None,
        )
        await query.answer("❌ Diese Fahrt ist nicht für dich.", show_alert=True)
        return

    # Validate trigger is allowed for current state
    allowed_triggers = TRIGGER_MAP.get(trip.status, [])
    if trigger not in allowed_triggers:
        logger.warning(
            "Invalid transition attempted",
            trip_id=trip_id,
            current_state=trip.status,
            trigger=trigger,
            allowed=allowed_triggers,
        )
        await query.answer(
            f"❌ Aktion »{trigger}« ist im Status »{trip.status}« nicht möglich.",
            show_alert=True,
        )
        return

    # Run state machine transition
    previous_state = trip.status
    try:
        sm = TripStateMachine(trip)
        # Trigger the transition directly on the state machine model.
        # The `transitions` library dynamically adds trigger methods to the model
        # (e.g. sm.losfahren(), sm.abschliessen()). We use getattr for dynamic dispatch.
        getattr(sm, trigger)()
        new_state = sm.state  # type: ignore[attr-defined]
    except Exception as exc:
        logger.exception(
            "State machine transition failed",
            trip_id=trip_id,
            trigger=trigger,
            from_state=previous_state,
        )
        await query.answer(
            f"❌ Übergang fehlgeschlagen: {exc}",
            show_alert=True,
        )
        return

    # Persist state change to database
    trip.status = new_state
    await trip.save()

    # Log event for audit trail
    await TripEvent.create(
        trip_id=trip.id,
        event_type="status_change",
        message=f"{previous_state} → {new_state} (via {trigger}, driver={driver.name})",
    )

    # Load patient for message formatting
    patient = await trip.patient
    patient_name = patient.name if patient else "?"
    vehicle_type = patient.vehicle_type if patient else "Sitz"

    # Build updated message with new state and keyboard
    new_text = format_trip_info(trip, patient_name, vehicle_type)
    new_keyboard = build_trip_keyboard_for_trip(trip_id, new_state)

    if new_keyboard:
        await query.edit_message_text(
            new_text,
            reply_markup=new_keyboard,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
    else:
        # Terminal state — remove keyboard
        await query.edit_message_text(
            new_text,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

    logger.info(
        "Trip state transition",
        trip_id=trip_id,
        driver=driver.name,
        trigger=trigger,
        transition=f"{previous_state} → {new_state}",
    )


# ── Public API: send trip to driver ───────────────────────────────────

async def send_trip_to_driver(
    app: Application,
    trip: Trip,
    driver: Driver,
) -> None:
    """Send a trip notification with inline keyboard to the assigned driver.

    Called by the dispatch/assignment flow when a trip is assigned.
    Only the assigned driver receives the message.
    """
    patient = await trip.patient
    patient_name = patient.name if patient else "?"
    vehicle_type = patient.vehicle_type if patient else "Sitz"

    text = format_trip_info(trip, patient_name, vehicle_type)
    keyboard = build_trip_keyboard_for_trip(trip.id, trip.status)

    try:
        await app.bot.send_message(
            chat_id=driver.telegram_id,
            text=text,
            reply_markup=keyboard,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        logger.info(
            "Trip notification sent to driver",
            trip_id=trip.id,
            driver=driver.name,
            driver_id=driver.telegram_id,
        )
    except Exception:
        logger.exception(
            "Failed to send trip notification",
            trip_id=trip.id,
            driver_id=driver.telegram_id,
        )


# ── Voice message handler ──────────────────────────────────────────────

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice messages from drivers: transcribe → intent → status update.

    Pipeline:
      1. Look up the driver by Telegram ID.
      2. Download the voice message audio file from Telegram.
      3. Transcribe the audio to German text via faster-whisper.
      4. Extract driver intent (action + trigger) from the transcript.
      5. If a valid trigger is found, advance the driver's active trip.
      6. Respond to the driver with the result.
    """
    telegram_id = update.effective_user.id if update.effective_user else 0
    voice = update.message.voice

    if voice is None:
        await update.message.reply_text("❌ Keine Sprachnachricht erkannt.")
        return

    # 1. Look up driver
    try:
        driver = await Driver.get(telegram_id=telegram_id)
    except DoesNotExist:
        await update.message.reply_text(
            "❌ Du bist nicht als Fahrer registriert. "
            "Bitte wende dich an deinen Disponenten."
        )
        return

    # Acknowledge receipt
    status_msg = await update.message.reply_text("🎙 Transkribiere Sprachnachricht...")

    try:
        # 2. Download voice file from Telegram
        voice_file = await context.bot.get_file(voice.file_id)
        audio_bytes = await voice_file.download_as_bytearray()
        audio_bytes = bytes(audio_bytes)
    except Exception:
        logger.exception("Failed to download voice message", telegram_id=telegram_id)
        await status_msg.edit_text("❌ Fehler beim Herunterladen der Sprachnachricht.")
        return

    # 3. Transcribe
    try:
        transcript = await transcribe_voice(audio_bytes)
    except Exception:
        logger.exception("Voice transcription failed", telegram_id=telegram_id)
        await status_msg.edit_text("❌ Fehler bei der Spracherkennung.")
        return

    if not transcript or not transcript.strip():
        await status_msg.edit_text(
            "❌ Sprachnachricht konnte nicht transkribiert werden. "
            "Bitte sprich deutlicher oder nutze die Buttons."
        )
        return

    # 4. Extract intent
    intent = await extract_driver_intent(transcript)

    # 5. Act on intent
    if intent.trigger is not None:
        # Trip-related action — find driver's active trip
        try:
            trip = await _get_active_trip_for_driver(driver)
            if trip is None:
                await status_msg.edit_text(
                    f"💬 Transkript: _{transcript}_\n\n"
                    f"Erkannt: *{intent.action}*\n\n"
                    "⚠️ Keine aktive Fahrt gefunden. Nutze /heute für deine Fahrten.",
                    parse_mode="Markdown",
                )
                return

            # Validate trigger is allowed for current trip status
            allowed_triggers = TRIGGER_MAP.get(trip.status, [])
            if intent.trigger not in allowed_triggers:
                await status_msg.edit_text(
                    f"💬 Transkript: _{transcript}_\n\n"
                    f"Erkannt: *{intent.action}*\n\n"
                    f"⚠️ Aktion »{intent.trigger}« ist im Status »{trip.status}« "
                    f"nicht möglich.\nErlaubt: {', '.join(allowed_triggers)}",
                    parse_mode="Markdown",
                )
                return

            # Execute state transition
            previous_state = trip.status
            sm = TripStateMachine(trip)
            getattr(sm, intent.trigger)()
            new_state = sm.state

            trip.status = new_state
            await trip.save()

            await TripEvent.create(
                trip_id=trip.id,
                event_type="status_change",
                message=(
                    f"{previous_state} → {new_state} "
                    f"(via voice: {intent.action}, driver={driver.name})"
                ),
            )

            patient = await trip.patient
            patient_name = patient.name if patient else "?"

            await status_msg.edit_text(
                f"💬 _{transcript}_\n\n"
                f"✅ *{intent.action}* — Fahrt #{trip.id}\n"
                f"👤 {patient_name}\n"
                f"📊 Status: {previous_state} → *{new_state}*",
                parse_mode="Markdown",
            )

            logger.info(
                "Voice-driven status update",
                driver=driver.name,
                trip_id=trip.id,
                transcript=transcript[:80],
                intent=intent.action,
                transition=f"{previous_state} → {new_state}",
            )

        except Exception:
            logger.exception(
                "Voice handler trip update failed",
                driver=driver.name,
                intent=intent.action,
            )
            await status_msg.edit_text(
                f"💬 _{transcript}_\n\n"
                f"Erkannt: *{intent.action}*\n\n"
                "❌ Fehler beim Aktualisieren der Fahrt.",
                parse_mode="Markdown",
            )

    elif intent.action == "pause":
        # Handle pause via voice — reuse the /pause command logic
        active_break = await DriverBreak.filter(
            driver_id=driver.id, end_time__isnull=True
        ).first()

        if active_break is None:
            await DriverBreak.create(driver=driver, start_time=_now())
            await status_msg.edit_text(
                f"💬 _{transcript}_\n\n☕ *Pause gestartet* — viel Erholung!",
                parse_mode="Markdown",
            )
        else:
            active_break.end_time = _now()
            await active_break.save()
            duration = int(
                (active_break.end_time - active_break.start_time).total_seconds() / 60
            )
            await status_msg.edit_text(
                f"💬 _{transcript}_\n\n✅ *Pause beendet* ({duration} Min.)",
                parse_mode="Markdown",
            )

    else:
        # Unknown or unactionable intent
        await status_msg.edit_text(
            f"💬 _{transcript}_\n\n"
            f"🤷 Keine klare Fahraktion erkannt.\n"
            f"Bitte sprich eine Aktion wie 'losfahren', 'angekommen', "
            f"'abgesetzt' oder nutze die Buttons.",
            parse_mode="Markdown",
        )


async def _get_active_trip_for_driver(driver: Driver) -> Trip | None:
    """Find the driver's currently active trip (not terminal, not cancelled).

    Returns the most recently updated non-terminal trip assigned to this driver.
    """
    active_statuses = [
        "zugewiesen", "anfahrt", "angekommen",
        "patient_an_bord", "unterwegs", "abgesetzt",
        "problem",
    ]
    trips = await Trip.filter(
        driver_id=driver.id,
        status__in=active_statuses,
    ).order_by("-scheduled_pickup").limit(1)

    return trips[0] if trips else None


# ── Natural language handler (text) ────────────────────────────────────

async def handle_natural_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle natural language text messages: classify intent via NLU, route."""
    text = update.message.text.strip()
    if not text:
        return

    from krankenfahrt.services.nlu import classify_driver

    intent = await classify_driver(text)
    logger.info("Driver NLU: %s → intent=%s (%.2f)", text[:60], intent.intent, intent.confidence)

    if intent.intent == "heute":
        await cmd_heute(update, context)
    elif intent.intent == "pause":
        await cmd_pause(update, context)
    elif intent.intent == "status":
        # Route to voice handler's status logic (reuse the pipeline)
        await update.message.reply_text(
            "📋 Für Status-Updates nutze bitte die Buttons unter deiner aktiven Fahrt, "
            "oder schick eine Sprachnachricht („Bin angekommen\", „Patient an Bord\" etc.)."
        )
    elif intent.intent == "problem":
        await update.message.reply_text(
            "⚠️ *Problem melden* — bitte beschreibe das Problem kurz.\n"
            "Ich informiere dann den Disponenten.",
            parse_mode="Markdown",
        )
    elif intent.intent == "info":
        await update.message.reply_text(
            "🚗 *Fahrer-Bot*\n\n"
            "Sprich einfach mit mir!\n"
            "\"Was hab ich heute?\" → Tagesübersicht\n"
            "\"Ich mach Pause\" → Pause starten\n"
            "\"Bin zurück\" → wieder bereit\n\n"
            "Oder: /heute • /pause • Sprachnachricht"
        )
    else:
        await update.message.reply_text(
            "❓ Sag einfach was du brauchst — \"Was hab ich heute?\", "
            "\"Ich mach Pause\", oder sprich eine Sprachnachricht."
        )


# ── Handler registration ──────────────────────────────────────────────

def register_handlers(app: Application) -> None:
    """Register all driver-bot command and callback handlers."""
    # Natural language text (catches non-command text)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_natural_message))
    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("heute", cmd_heute))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CallbackQueryHandler(handle_trip_callback, pattern=f"^{CALLBACK_PREFIX}:"))
    # Voice message handler — full pipeline: transcribe → intent → status update
    app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    logger.info("Driver-Bot handlers registered: NLU + start, heute, pause, trip_callback, voice")
