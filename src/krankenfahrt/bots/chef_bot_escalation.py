"""Escalation commands for Chef-Bot (@FahrtenChef).

Provides:
  /eskalieren      — Manual escalation trigger for a trip
  /eskalationen    — List all open escalations
  /eskalation_log  — Query escalation audit log

Wired into the Chef-Bot via register_handlers().
"""

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from krankenfahrt.core.escalation import (
    ESCALATION_OPTIONS,
    create_escalation,
    get_escalation_log,
    get_open_escalations,
    process_escalation_option,
)
from krankenfahrt.models.schema import Escalation

logger = structlog.get_logger(__name__)

EM_DASH = "\u2014"  # Unicode em dash, avoids f-string backslash issues on 3.11

# Status formatting for display
STATUS_FMT = {
    "open": "\U0001f534 Offen",
    "acknowledged": "\U0001f7e1 Quittiert",
    "resolved": "\U0001f7e2 Gel\u00f6st",
}

TRIGGER_FMT = {
    "timeout": "\u23f0 Timeout",
    "manual": "\U0001f464 Manuell",
    "system": "\U0001f916 System",
}


def _parse_trip_id(text: str) -> int | None:
    """Parse a trip ID from text, returning None on failure."""
    try:
        return int(text.strip())
    except (ValueError, TypeError):
        return None


# --- Command Handlers ---


async def cmd_eskalieren(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Manually escalate a trip. Usage: /eskalieren <trip_id> [reason]"""
    args = context.args

    if not args:
        await update.message.reply_text(
            "Usage: `/eskalieren <trip_id> [grund]`\n"
            "z.B. `/eskalieren 42 Fahrer kommt zu sp\u00e4t`",
            parse_mode="Markdown",
        )
        return

    trip_id = _parse_trip_id(args[0])
    if trip_id is None:
        await update.message.reply_text(
            "Ung\u00fcltige Trip-ID. Bitte eine Zahl angeben."
        )
        return

    reason = " ".join(args[1:]) if len(args) > 1 else "Manuelle Eskalation durch Chef"

    try:
        esc = await create_escalation(
            trip_id=trip_id,
            trigger_reason="manual",
            trigger_detail=reason,
        )
    except ValueError as e:
        await update.message.reply_text(str(e))
        return

    # Present escalation options as inline keyboard
    keyboard = [
        [
            InlineKeyboardButton(label, callback_data=f"esc_opt:{esc.id}:{option}")
            for option, label in [
                ("reassign", "Neu zuweisen"),
                ("pause", "Pausieren"),
            ]
        ],
        [
            InlineKeyboardButton(label, callback_data=f"esc_opt:{esc.id}:{option}")
            for option, label in [
                ("cancel", "Stornieren"),
                ("acknowledge", "Quittieren"),
            ]
        ],
        [
            InlineKeyboardButton(
                "L\u00f6sen", callback_data=f"esc_opt:{esc.id}:resolve"
            ),
        ],
    ]

    await update.message.reply_text(
        f"Eskalation #{esc.id} erstellt\n\n"
        f"Fahrt: #{trip_id}\n"
        f"Grund: {reason}\n"
        f"Status: {STATUS_FMT[esc.status]}\n\n"
        f"Bitte w\u00e4hle eine Option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def cmd_eskalationen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all open escalations. Usage: /eskalationen"""
    try:
        escalations = await get_open_escalations()
    except Exception as e:
        logger.exception("eskalationen_query_failed")
        await update.message.reply_text(f"Fehler beim Abrufen: {e}")
        return

    if not escalations:
        await update.message.reply_text("Keine offenen Eskalationen.")
        return

    for esc in escalations:
        trip = await esc.trip
        patient = await trip.patient if trip else None
        patient_name = patient.name if patient else "Unbekannt"

        msg = (
            f"*Eskalation #{esc.id}* {EM_DASH} Fahrt #{esc.trip_id} ({patient_name})\n"
            f"  Ausl\u00f6ser: {TRIGGER_FMT[esc.trigger_reason]}\n"
            f"  Status: {STATUS_FMT[esc.status]}\n"
            f"  Erstellt: {esc.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"  Grund: {esc.trigger_detail or EM_DASH}"
        )

        if esc.status != "resolved":
            keyboard = [[InlineKeyboardButton(
                "Option w\u00e4hlen",
                callback_data=f"esc_show:{esc.id}",
            )]]
            await update.message.reply_text(
                msg,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_eskalation_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Query escalation audit log. Usage: /eskalation_log [trip_id]"""
    args = context.args

    trip_id = None
    if args:
        trip_id = _parse_trip_id(args[0])
        if trip_id is None:
            await update.message.reply_text(
                "Ung\u00fcltige Trip-ID. Bitte eine Zahl angeben."
            )
            return

    try:
        log = await get_escalation_log(trip_id=trip_id, limit=20)
    except Exception as e:
        logger.exception("eskalation_log_query_failed")
        await update.message.reply_text(f"Fehler beim Abrufen des Logs: {e}")
        return

    if not log:
        if trip_id:
            await update.message.reply_text(
                f"Keine Eskalationen f\u00fcr Fahrt #{trip_id} gefunden."
            )
        else:
            await update.message.reply_text("Keine Eskalationen gefunden.")
        return

    title = (
        f"*Eskalations-Log f\u00fcr Fahrt #{trip_id}*"
        if trip_id
        else "*Eskalations-Log (letzte 20)*"
    )
    lines = [title, ""]

    for esc in log:
        trip = await esc.trip
        patient = await trip.patient if trip else None
        patient_name = patient.name if patient else "Unbekannt"

        parts = [
            f"*#{esc.id}* {EM_DASH} Fahrt #{esc.trip_id} ({patient_name})",
            f"  Ausl\u00f6ser: {TRIGGER_FMT[esc.trigger_reason]}",
            f"  Status: {STATUS_FMT[esc.status]}",
            f"  Option: {esc.chosen_option or EM_DASH}",
            f"  Erstellt: {esc.created_at.strftime('%d.%m.%Y %H:%M')}",
        ]
        if esc.trigger_detail:
            parts.append(f"  Grund: {esc.trigger_detail}")
        if esc.resolution_note:
            parts.append(f"  Notiz: {esc.resolution_note}")
        if esc.resolved_at:
            parts.append(f"  Gel\u00f6st: {esc.resolved_at.strftime('%d.%m.%Y %H:%M')}")

        lines.append("\n".join(parts) + "\n")

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:4000] + "\n\n... (gek\u00fcrzt)"
    await update.message.reply_text(msg, parse_mode="Markdown")


# --- Callback Handler ---


async def callback_escalation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button presses for escalation options."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("esc_opt:"):
        parts = data.split(":")
        if len(parts) != 3:
            await query.edit_message_text("Ung\u00fcltige Aktion.")
            return

        esc_id = int(parts[1])
        option = parts[2]
        telegram_id = query.from_user.id

        try:
            esc_result = await process_escalation_option(
                escalation_id=esc_id,
                option=option,
                telegram_id=telegram_id,
            )
        except ValueError as e:
            await query.edit_message_text(str(e))
            return

        label = ESCALATION_OPTIONS.get(option, option)
        trip = await esc_result.trip
        patient = await trip.patient if trip else None
        patient_name = patient.name if patient else "Unbekannt"

        await query.edit_message_text(
            f"*Eskalation #{esc_result.id} bearbeitet*\n\n"
            f"Fahrt: #{esc_result.trip_id} ({patient_name})\n"
            f"Option: {label}\n"
            f"Status: {STATUS_FMT[esc_result.status]}\n"
            f"Ausgef\u00fchrt von: {query.from_user.first_name}",
            parse_mode="Markdown",
        )

    elif data.startswith("esc_show:"):
        esc_id = int(data.split(":")[1])

        try:
            esc = await Escalation.get_or_none(id=esc_id)
            if esc is None:
                await query.edit_message_text("Eskalation nicht gefunden.")
                return

            if esc.status == "resolved":
                await query.edit_message_text(
                    "Diese Eskalation wurde bereits gel\u00f6st."
                )
                return

            trip = await esc.trip
            patient = await trip.patient if trip else None
            patient_name = patient.name if patient else "Unbekannt"

            keyboard = [
                [
                    InlineKeyboardButton(
                        label, callback_data=f"esc_opt:{esc.id}:{option}"
                    )
                    for option, label in [
                        ("reassign", "Neu zuweisen"),
                        ("pause", "Pausieren"),
                    ]
                ],
                [
                    InlineKeyboardButton(
                        label, callback_data=f"esc_opt:{esc.id}:{option}"
                    )
                    for option, label in [
                        ("cancel", "Stornieren"),
                        ("acknowledge", "Quittieren"),
                    ]
                ],
                [
                    InlineKeyboardButton(
                        "L\u00f6sen", callback_data=f"esc_opt:{esc.id}:resolve"
                    ),
                ],
            ]

            await query.edit_message_text(
                f"*Eskalation #{esc.id}*\n\n"
                f"Fahrt: #{esc.trip_id} ({patient_name})\n"
                f"Ausl\u00f6ser: {TRIGGER_FMT[esc.trigger_reason]}\n"
                f"Grund: {esc.trigger_detail or EM_DASH}\n"
                f"Status: {STATUS_FMT[esc.status]}\n\n"
                f"Bitte w\u00e4hle eine Option:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.exception("esc_show_callback_failed")
            await query.edit_message_text(f"Fehler: {e}")


# --- Registration ---


def register_handlers(app: Application) -> None:
    """Register all escalation command handlers on the Chef-Bot app."""
    app.add_handler(CommandHandler("eskalieren", cmd_eskalieren))
    app.add_handler(CommandHandler("eskalationen", cmd_eskalationen))
    app.add_handler(CommandHandler("eskalation_log", cmd_eskalation_log))
    app.add_handler(
        CallbackQueryHandler(callback_escalation, pattern=r"^esc_(opt|show):")
    )
    logger.info(
        "Escalation handlers registered: eskalieren, eskalationen, eskalation_log"
    )
