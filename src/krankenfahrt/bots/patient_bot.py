"""Patient-Bot (@FahrGast): Patient self-service interface.

Commands:
  /start          — Welcome, registration, profile summary
  /profil         — View personal profile (Stammdaten)
  /profil_edit    — Start profile editing conversation
  /vorlagen       — List recurring trip templates
  /vorlage_neu    — Start new template creation conversation
  /vorlage_show N — Show template detail (N = template ID)
  /vorlage_edit N — Start template editing conversation
  /vorlage_del N  — Delete template with confirmation

Authorization:
  - Patients can only view/edit their own profile and templates.
  - Admins (config.ADMIN_TELEGRAM_IDS) can view/edit any patient's data.
  - Admin override: /profil_as <telegram_id> to view another patient's profile.
"""

import logging
from datetime import time as dtime
from typing import cast

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from tortoise.exceptions import DoesNotExist

from krankenfahrt.config import config
from krankenfahrt.models.schema import Patient, RecurringTrip, Trip
from krankenfahrt.services.llm import extract_booking_intent

logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────
(
    PROFILE_EDIT_NAME,
    PROFILE_EDIT_PHONE,
    PROFILE_EDIT_PICKUP,
    PROFILE_EDIT_DEST,
    PROFILE_EDIT_INSURANCE_PROVIDER,
    PROFILE_EDIT_INSURANCE_NUMBER,
    PROFILE_EDIT_VEHICLE_TYPE,
    PROFILE_EDIT_SPECIAL_NEEDS,
    PROFILE_EDIT_NOTES,
) = range(9)

(
    TEMPLATE_NEW_PICKUP,
    TEMPLATE_NEW_DEST,
    TEMPLATE_NEW_DAYS,
    TEMPLATE_NEW_PICKUP_TIME,
    TEMPLATE_NEW_RETURN_TIME,
    TEMPLATE_NEW_VEHICLE_TYPE,
    TEMPLATE_NEW_CONFIRM,
) = range(9, 16)

(
    TEMPLATE_EDIT_SELECT_FIELD,
    TEMPLATE_EDIT_NEW_VALUE,
) = range(16, 18)


# ── Authorization helpers ──────────────────────────────────────────────────

def _is_admin(telegram_id: int) -> bool:
    """Check whether the given Telegram user is an admin (dispatcher/owner)."""
    return telegram_id in config.ADMIN_TELEGRAM_IDS


async def _resolve_target_patient(
    telegram_id: int,
    admin_viewing_id: int | None = None,
) -> Patient | None:
    """Return the patient record the user is allowed to access.

    If admin_viewing_id is set (admin viewing another patient), return that patient.
    Otherwise, return the patient matching telegram_id.
    Admins can access any patient; regular patients only their own.
    """
    if admin_viewing_id is not None:
        return await Patient.filter(telegram_id=admin_viewing_id).first()
    return await Patient.filter(telegram_id=telegram_id).first()


def _can_modify(requesting_telegram_id: int, patient_telegram_id: int) -> bool:
    """Return True if requesting user can modify the given patient's data."""
    if _is_admin(requesting_telegram_id):
        return True
    return requesting_telegram_id == patient_telegram_id


async def _resolve_template(
    template_id: int,
    requesting_telegram_id: int,
) -> tuple[RecurringTrip | None, str | None]:
    """Fetch a template and check ownership.

    Returns (template, error_message). If error_message is set, template is None.
    """
    try:
        template = await RecurringTrip.get(id=template_id).prefetch_related("patient")
    except DoesNotExist:
        return None, f"❌ Vorlage #{template_id} existiert nicht."

    patient = cast(Patient, template.patient)
    if not _can_modify(requesting_telegram_id, patient.telegram_id):
        return None, "⛔ Keine Berechtigung für diese Vorlage."

    return template, None


def _format_profile(patient: Patient) -> str:
    """Format a patient profile as readable text."""
    return (
        f"👤 *Dein Profil* (ID: {patient.id})\n\n"
        f"*Name:* {patient.name}\n"
        f"*Telefon:* {patient.phone or '—'}\n"
        f"*Standard-Abholadresse:* {patient.default_pickup_addr}\n"
        f"*Standard-Ziel:* {patient.default_dest_addr or '—'}\n"
        f"*Krankenkasse:* {patient.insurance_provider or '—'}\n"
        f"*Vers.-Nr.:* {patient.insurance_number or '—'}\n"
        f"*Fahrzeugtyp:* {patient.vehicle_type}\n"
        f"*Besondere Bedürfnisse:* {patient.special_needs or '—'}\n"
        f"*Notizen:* {patient.notes or '—'}"
    )


def _fmt_time(val) -> str:
    """Format a time value as HH:MM, handling both datetime.time objects and strings."""
    if val is None:
        return "—"
    if isinstance(val, str):
        return val[:5]  # Already "HH:MM"
    return val.strftime("%H:%M")  # datetime.time


def _format_template(template: RecurringTrip) -> str:
    """Format a recurring trip template as readable text."""
    return (
        f"🔁 *Vorlage #{template.id}*\n\n"
        f"*Abholung:* {template.pickup_addr}\n"
        f"*Ziel:* {template.dest_addr}\n"
        f"*Tage:* {template.cron_days}\n"
        f"*Abholzeit:* {_fmt_time(template.pickup_time)}\n"
        f"*Rückfahrt:* {_fmt_time(template.return_time)}\n"
        f"*Fahrzeugtyp:* {template.vehicle_type}\n"
        f"*Aktiv bis:* {template.active_until.strftime('%d.%m.%Y') if template.active_until else 'unbegrenzt'}"
    )


# ── /start ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Welcome message + auto-registration if new patient, or show profile."""
    if update.effective_user is None or update.message is None:
        return

    telegram_id = update.effective_user.id
    patient = await Patient.filter(telegram_id=telegram_id).first()

    if patient is None:
        # New patient — auto-register with defaults
        patient = await Patient.create(
            telegram_id=telegram_id,
            name=update.effective_user.full_name,
            default_pickup_addr="(bitte ergänzen)",
        )
        await update.message.reply_text(
            "🚑 *Willkommen bei Krankenfahrt!*\n\n"
            "Dein Profil wurde automatisch angelegt. Bitte ergänze deine Daten "
            "mit /profil_edit, damit wir deine Fahrten optimal planen können.\n\n"
            "📋 *Verfügbare Befehle:*\n"
            "/profil — Profil anzeigen\n"
            "/profil_edit — Profil bearbeiten\n"
            "/vorlagen — Wiederkehrende Fahrten anzeigen\n"
            "/vorlage_neu — Neue Vorlage erstellen\n"
            "/vorlage_show <ID> — Vorlage anzeigen\n"
            "/vorlage_edit <ID> — Vorlage bearbeiten\n"
            "/vorlage_del <ID> — Vorlage löschen",
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info("New patient registered: telegram_id=%d, name=%s",
                     telegram_id, update.effective_user.full_name)
        return

    # Existing patient — show profile
    await update.message.reply_text(
        f"🚑 *Willkommen zurück, {patient.name}!*\n\n{_format_profile(patient)}\n\n"
        "Nutze die Befehle unten, um deine Daten zu verwalten.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /profil (view) ─────────────────────────────────────────────────────────

async def cmd_profil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the patient's profile."""
    if update.effective_user is None or update.message is None:
        return

    telegram_id = update.effective_user.id
    patient = await _resolve_target_patient(telegram_id)

    if patient is None:
        await update.message.reply_text(
            "❌ Kein Profil gefunden. Nutze /start zur Registrierung."
        )
        return

    await update.message.reply_text(
        _format_profile(patient),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /profil_edit conversation ──────────────────────────────────────────────

async def profil_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start profile editing — verify auth and ask for name."""
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END

    telegram_id = update.effective_user.id
    patient = await _resolve_target_patient(telegram_id)

    if patient is None:
        await update.message.reply_text(
            "❌ Kein Profil gefunden. Nutze /start zur Registrierung."
        )
        return ConversationHandler.END

    if not _can_modify(telegram_id, patient.telegram_id):
        await update.message.reply_text("⛔ Keine Berechtigung.")
        return ConversationHandler.END

    context.user_data["edit_patient_id"] = patient.id
    context.user_data["edit_telegram_id"] = patient.telegram_id

    await update.message.reply_text(
        f"Aktueller Name: *{patient.name}*\n\n"
        "Bitte neuen Namen eingeben (oder /skip zum Überspringen):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return PROFILE_EDIT_NAME


async def profil_edit_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Save name and ask for phone."""
    if update.message is None:
        return PROFILE_EDIT_NAME
    if update.message.text and update.message.text != "/skip":
        context.user_data["profile_name"] = update.message.text
    await update.message.reply_text(
        "Bitte Telefonnummer eingeben (oder /skip):"
    )
    return PROFILE_EDIT_PHONE


async def profil_edit_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return PROFILE_EDIT_PHONE
    if update.message.text and update.message.text != "/skip":
        context.user_data["profile_phone"] = update.message.text
    await update.message.reply_text(
        "Bitte Standard-Abholadresse eingeben (oder /skip):"
    )
    return PROFILE_EDIT_PICKUP


async def profil_edit_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return PROFILE_EDIT_PICKUP
    if update.message.text and update.message.text != "/skip":
        context.user_data["profile_pickup"] = update.message.text
    await update.message.reply_text(
        "Bitte Standard-Zieladresse eingeben (oder /skip):"
    )
    return PROFILE_EDIT_DEST


async def profil_edit_dest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return PROFILE_EDIT_DEST
    if update.message.text and update.message.text != "/skip":
        context.user_data["profile_dest"] = update.message.text
    await update.message.reply_text(
        "Bitte Krankenkasse eingeben (oder /skip):"
    )
    return PROFILE_EDIT_INSURANCE_PROVIDER


async def profil_edit_insurance_provider(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message is None:
        return PROFILE_EDIT_INSURANCE_PROVIDER
    if update.message.text and update.message.text != "/skip":
        context.user_data["profile_insurance_provider"] = update.message.text
    await update.message.reply_text(
        "Bitte Versicherungsnummer eingeben (oder /skip):"
    )
    return PROFILE_EDIT_INSURANCE_NUMBER


async def profil_edit_insurance_number(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message is None:
        return PROFILE_EDIT_INSURANCE_NUMBER
    if update.message.text and update.message.text != "/skip":
        context.user_data["profile_insurance_number"] = update.message.text
    await update.message.reply_text(
        "Bitte Fahrzeugtyp wählen (Sitz | Liege | Rad | KTW) — oder /skip:"
    )
    return PROFILE_EDIT_VEHICLE_TYPE


async def profil_edit_vehicle_type(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message is None:
        return PROFILE_EDIT_VEHICLE_TYPE
    if update.message.text and update.message.text != "/skip":
        vt = update.message.text.strip()
        if vt in ("Sitz", "Liege", "Rad", "KTW"):
            context.user_data["profile_vehicle_type"] = vt
        else:
            await update.message.reply_text(
                "⚠️ Ungültiger Typ. Bitte Sitz, Liege, Rad oder KTW eingeben:"
            )
            return PROFILE_EDIT_VEHICLE_TYPE
    await update.message.reply_text(
        "Besondere Bedürfnisse (z.B. Rollstuhl, Sauerstoff) — oder /skip:"
    )
    return PROFILE_EDIT_SPECIAL_NEEDS


async def profil_edit_special_needs(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message is None:
        return PROFILE_EDIT_SPECIAL_NEEDS
    if update.message.text and update.message.text != "/skip":
        context.user_data["profile_special_needs"] = update.message.text
    await update.message.reply_text(
        "Weitere Notizen (oder /skip):"
    )
    return PROFILE_EDIT_NOTES


async def profil_edit_notes(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Save final notes and persist all changes to DB."""
    if update.message is None:
        return PROFILE_EDIT_NOTES
    if update.message.text and update.message.text != "/skip":
        context.user_data["profile_notes"] = update.message.text

    # Persist to DB
    patient_id = context.user_data.get("edit_patient_id")
    patient = await Patient.get(id=patient_id)

    field_updates = {
        "name": "profile_name",
        "phone": "profile_phone",
        "default_pickup_addr": "profile_pickup",
        "default_dest_addr": "profile_dest",
        "insurance_provider": "profile_insurance_provider",
        "insurance_number": "profile_insurance_number",
        "vehicle_type": "profile_vehicle_type",
        "special_needs": "profile_special_needs",
        "notes": "profile_notes",
    }

    for db_field, ctx_key in field_updates.items():
        if ctx_key in context.user_data:
            setattr(patient, db_field, context.user_data[ctx_key])

    await patient.save()

    # Clean up context
    for key in list(context.user_data.keys()):
        if key.startswith("profile_") or key.startswith("edit_"):
            del context.user_data[key]

    await update.message.reply_text(
        "✅ *Profil gespeichert!*\n\n" + _format_profile(patient),
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


async def profil_edit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel profile editing."""
    if update.message:
        await update.message.reply_text("❌ Profilbearbeitung abgebrochen.")
    # Clean up
    for key in list(context.user_data.keys()):
        if key.startswith("profile_") or key.startswith("edit_"):
            del context.user_data[key]
    return ConversationHandler.END


# ── /vorlagen (list) ───────────────────────────────────────────────────────

async def cmd_vorlagen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List all recurring trip templates for the patient."""
    if update.effective_user is None or update.message is None:
        return

    telegram_id = update.effective_user.id
    patient = await _resolve_target_patient(telegram_id)

    if patient is None:
        await update.message.reply_text(
            "❌ Kein Profil gefunden. Nutze /start zur Registrierung."
        )
        return

    templates = await RecurringTrip.filter(patient=patient).all()

    if not templates:
        await update.message.reply_text(
            "📋 *Keine Vorlagen vorhanden.*\n\n"
            "Nutze `/vorlage_neu`, um eine wiederkehrende Fahrt anzulegen "
            "(z.B. Dialyse jeden Mo/Mi/Fr).",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    lines = [f"📋 *Deine Vorlagen ({len(templates)})*\n"]
    for tpl in templates:
        active = "✅" if tpl.active_until is None or tpl.active_until >= dtime.now().date() else "⏸️"
        lines.append(
            f"{active} #{tpl.id}: {tpl.pickup_addr[:30]} → {tpl.dest_addr[:30]}\n"
            f"   _{tpl.cron_days} um {_fmt_time(tpl.pickup_time)}_"
        )

    lines.append(
        "\n/vorlage_show \\<ID\\> — Details anzeigen\n"
        "/vorlage_edit \\<ID\\> — Bearbeiten\n"
        "/vorlage_del \\<ID\\> — Löschen\n"
        "/vorlage_neu — Neue Vorlage"
    )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /vorlage_show <id> ─────────────────────────────────────────────────────

async def cmd_vorlage_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a single recurring trip template detail."""
    if update.effective_user is None or update.message is None:
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "ℹ️ Nutzung: `/vorlage_show <ID>`\n\n"
            "Die ID findest du in `/vorlagen`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        template_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Ungültige ID. Bitte Zahl angeben.")
        return

    template, error = await _resolve_template(template_id, update.effective_user.id)
    if error:
        await update.message.reply_text(error)
        return

    await update.message.reply_text(
        _format_template(template),
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /vorlage_del <id> ──────────────────────────────────────────────────────

async def cmd_vorlage_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete a recurring trip template with inline confirmation."""
    if update.effective_user is None or update.message is None:
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "ℹ️ Nutzung: `/vorlage_del <ID>`\n\n"
            "Die ID findest du in `/vorlagen`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        template_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Ungültige ID. Bitte Zahl angeben.")
        return

    template, error = await _resolve_template(template_id, update.effective_user.id)
    if error:
        await update.message.reply_text(error)
        return

    # Store in context for callback handling
    context.user_data["del_template_id"] = template_id

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Ja, löschen", callback_data=f"tpl_del_confirm_{template_id}"),
            InlineKeyboardButton("❌ Abbrechen", callback_data="tpl_del_cancel"),
        ]
    ])

    await update.message.reply_text(
        f"⚠️ *Vorlage #{template_id} wirklich löschen?*\n\n"
        f"{_format_template(template)}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def callback_vorlage_del_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle delete confirmation callback."""
    query = update.callback_query
    if query is None:
        return
    await query.answer()

    data = query.data or ""
    if data == "tpl_del_cancel":
        await query.edit_message_text("❌ Löschung abgebrochen.")
        return

    # Parse template_id from callback data: "tpl_del_confirm_<id>"
    try:
        template_id = int(data.split("_")[-1])
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Fehler beim Parsen der ID.")
        return

    template, error = await _resolve_template(
        template_id, update.effective_user.id if update.effective_user else 0
    )
    if error:
        await query.edit_message_text(error)
        return

    tpl_info = f"#{template.id}: {template.pickup_addr[:30]} → {template.dest_addr[:30]}"
    await template.delete()
    await query.edit_message_text(f"🗑️ *Vorlage gelöscht:* {tpl_info}", parse_mode=ParseMode.MARKDOWN)
    logger.info("Template deleted: id=%d", template_id)


# ── /vorlage_neu conversation ──────────────────────────────────────────────

async def vorlage_neu_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start new template creation — verify patient exists, ask for pickup address."""
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END

    telegram_id = update.effective_user.id
    patient = await _resolve_target_patient(telegram_id)

    if patient is None:
        await update.message.reply_text(
            "❌ Kein Profil gefunden. Nutze /start zur Registrierung."
        )
        return ConversationHandler.END

    context.user_data["tpl_patient_id"] = patient.id

    # Pre-fill with patient defaults if available
    if patient.default_pickup_addr:
        await update.message.reply_text(
            f"Standard-Abholadresse: *{patient.default_pickup_addr}*\n\n"
            "Neue Abholadresse eingeben (oder /skip für Standard):",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text("Bitte Abholadresse eingeben:")

    return TEMPLATE_NEW_PICKUP


async def vorlage_neu_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return TEMPLATE_NEW_PICKUP
    if update.message.text and update.message.text != "/skip":
        context.user_data["tpl_pickup"] = update.message.text
    await update.message.reply_text("Bitte Zieladresse eingeben:")
    return TEMPLATE_NEW_DEST


async def vorlage_neu_dest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return TEMPLATE_NEW_DEST
    if update.message.text:
        context.user_data["tpl_dest"] = update.message.text
    await update.message.reply_text(
        "Bitte Wochentage eingeben (z.B. *Mo,Mi,Fr*):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return TEMPLATE_NEW_DAYS


async def vorlage_neu_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None:
        return TEMPLATE_NEW_DAYS
    if update.message.text:
        context.user_data["tpl_days"] = update.message.text
    await update.message.reply_text(
        "Bitte Abholzeit eingeben (z.B. *08:30*):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return TEMPLATE_NEW_PICKUP_TIME


async def vorlage_neu_pickup_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message is None:
        return TEMPLATE_NEW_PICKUP_TIME
    if update.message.text:
        try:
            hour, minute = update.message.text.strip().split(":")
            context.user_data["tpl_pickup_time"] = dtime(int(hour), int(minute))
        except (ValueError, TypeError):
            await update.message.reply_text(
                "⚠️ Ungültiges Format. Bitte HH:MM eingeben (z.B. 08:30):"
            )
            return TEMPLATE_NEW_PICKUP_TIME
    await update.message.reply_text(
        "Bitte Rückfahrtzeit eingeben (oder /skip):"
    )
    return TEMPLATE_NEW_RETURN_TIME


async def vorlage_neu_return_time(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message is None:
        return TEMPLATE_NEW_RETURN_TIME
    if update.message.text and update.message.text != "/skip":
        try:
            hour, minute = update.message.text.strip().split(":")
            context.user_data["tpl_return_time"] = dtime(int(hour), int(minute))
        except (ValueError, TypeError):
            await update.message.reply_text(
                "⚠️ Ungültiges Format. Bitte HH:MM eingeben (z.B. 14:00) oder /skip:"
            )
            return TEMPLATE_NEW_RETURN_TIME
    await update.message.reply_text(
        "Fahrzeugtyp (Sitz | Liege | Rad | KTW) — oder /skip für Standard (Sitz):"
    )
    return TEMPLATE_NEW_VEHICLE_TYPE


async def vorlage_neu_vehicle_type(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    if update.message is None:
        return TEMPLATE_NEW_VEHICLE_TYPE
    if update.message.text and update.message.text != "/skip":
        vt = update.message.text.strip()
        if vt in ("Sitz", "Liege", "Rad", "KTW"):
            context.user_data["tpl_vehicle_type"] = vt
        else:
            await update.message.reply_text(
                "⚠️ Ungültiger Typ. Bitte Sitz, Liege, Rad oder KTW eingeben:"
            )
            return TEMPLATE_NEW_VEHICLE_TYPE

    # Build summary for confirmation
    pickup = context.user_data.get("tpl_pickup", "(nicht angegeben)")
    dest = context.user_data.get("tpl_dest", "(nicht angegeben)")
    days = context.user_data.get("tpl_days", "(nicht angegeben)")
    ptime = context.user_data.get("tpl_pickup_time", dtime(8, 0))
    rtime = context.user_data.get("tpl_return_time")
    vt = context.user_data.get("tpl_vehicle_type", "Sitz")

    if isinstance(ptime, dtime):
        ptime_str = ptime.strftime("%H:%M")
    else:
        ptime_str = str(ptime)

    summary = (
        f"📋 *Neue Vorlage — Bestätigung*\n\n"
        f"*Abholung:* {pickup}\n"
        f"*Ziel:* {dest}\n"
        f"*Tage:* {days}\n"
        f"*Abholzeit:* {ptime_str}\n"
        f"*Rückfahrt:* {rtime.strftime('%H:%M') if isinstance(rtime, dtime) else '—'}\n"
        f"*Fahrzeugtyp:* {vt}"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Erstellen", callback_data="tpl_new_confirm"),
            InlineKeyboardButton("❌ Abbrechen", callback_data="tpl_new_cancel"),
        ]
    ])

    await update.message.reply_text(
        summary,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )
    return TEMPLATE_NEW_CONFIRM


async def callback_vorlage_neu_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle new template confirmation callback — persist to DB."""
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()

    data = query.data or ""
    if data == "tpl_new_cancel":
        await query.edit_message_text("❌ Erstellung abgebrochen.")
        _clean_tpl_context(context)
        return ConversationHandler.END

    # Persist template
    patient_id = context.user_data.get("tpl_patient_id")
    patient = await Patient.get(id=patient_id)

    # Serialize time objects to "HH:MM" strings (SQLite can't bind datetime.time)
    def _serialize_time(t):
        if t is None:
            return None
        if isinstance(t, str):
            return t[:5]
        return t.strftime("%H:%M")

    template = await RecurringTrip.create(
        patient=patient,
        pickup_addr=context.user_data.get("tpl_pickup", ""),
        dest_addr=context.user_data.get("tpl_dest", ""),
        cron_days=context.user_data.get("tpl_days", ""),
        pickup_time=_serialize_time(context.user_data.get("tpl_pickup_time", dtime(8, 0))),
        return_time=_serialize_time(context.user_data.get("tpl_return_time")),
        vehicle_type=context.user_data.get("tpl_vehicle_type", "Sitz"),
    )

    await query.edit_message_text(
        f"✅ *Vorlage #{template.id} erstellt!*\n\n{_format_template(template)}",
        parse_mode=ParseMode.MARKDOWN,
    )
    logger.info("Template created: id=%d, patient=%d", template.id, patient_id)
    _clean_tpl_context(context)
    return ConversationHandler.END


def _clean_tpl_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove template-related keys from user_data."""
    for key in list(context.user_data.keys()):
        if key.startswith("tpl_"):
            del context.user_data[key]


async def vorlage_neu_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel new template creation."""
    if update.message:
        await update.message.reply_text("❌ Erstellung abgebrochen.")
    _clean_tpl_context(context)
    return ConversationHandler.END


# ── /vorlage_edit <id> conversation ────────────────────────────────────────

async def vorlage_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start template editing — verify ownership, present field selection."""
    if update.effective_user is None or update.message is None:
        return ConversationHandler.END

    args = context.args
    if not args:
        await update.message.reply_text(
            "ℹ️ Nutzung: `/vorlage_edit <ID>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return ConversationHandler.END

    try:
        template_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Ungültige ID.")
        return ConversationHandler.END

    template, error = await _resolve_template(template_id, update.effective_user.id)
    if error:
        await update.message.reply_text(error)
        return ConversationHandler.END

    context.user_data["edit_tpl_id"] = template_id

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📍 Abholadresse", callback_data="tpl_edit_pickup_addr")],
        [InlineKeyboardButton("🎯 Zieladresse", callback_data="tpl_edit_dest_addr")],
        [InlineKeyboardButton("📅 Tage", callback_data="tpl_edit_cron_days")],
        [InlineKeyboardButton("🕐 Abholzeit", callback_data="tpl_edit_pickup_time")],
        [InlineKeyboardButton("🕑 Rückfahrtzeit", callback_data="tpl_edit_return_time")],
        [InlineKeyboardButton("🚗 Fahrzeugtyp", callback_data="tpl_edit_vehicle_type")],
        [InlineKeyboardButton("❌ Abbrechen", callback_data="tpl_edit_cancel")],
    ])

    await update.message.reply_text(
        f"✏️ *Vorlage #{template_id} bearbeiten*\n\n{_format_template(template)}\n\n"
        "Welches Feld möchtest du ändern?",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )
    return TEMPLATE_EDIT_SELECT_FIELD


async def callback_tpl_edit_select(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Handle field selection for template editing."""
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()

    data = query.data or ""

    if data == "tpl_edit_cancel":
        await query.edit_message_text("❌ Bearbeitung abgebrochen.")
        return ConversationHandler.END

    # Extract field name from callback data: "tpl_edit_<field_name>"
    field_name = data.removeprefix("tpl_edit_")
    context.user_data["tpl_edit_field"] = field_name

    field_labels = {
        "pickup_addr": "neue Abholadresse",
        "dest_addr": "neue Zieladresse",
        "cron_days": "neue Wochentage (z.B. Mo,Mi,Fr)",
        "pickup_time": "neue Abholzeit (z.B. 08:30)",
        "return_time": "neue Rückfahrtzeit (z.B. 14:00) oder /skip für leer",
        "vehicle_type": "neuen Fahrzeugtyp (Sitz | Liege | Rad | KTW)",
    }

    label = field_labels.get(field_name, f"neuen Wert für {field_name}")
    await query.edit_message_text(f"Bitte {label} eingeben:")
    return TEMPLATE_EDIT_NEW_VALUE


async def vorlage_edit_new_value(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """Save the new value to the template."""
    if update.message is None:
        return TEMPLATE_EDIT_NEW_VALUE

    field_name = context.user_data.get("tpl_edit_field", "")
    template_id = context.user_data.get("edit_tpl_id")

    if not template_id:
        await update.message.reply_text("❌ Interner Fehler: Keine Template-ID.")
        return ConversationHandler.END

    try:
        template = await RecurringTrip.get(id=template_id)
    except DoesNotExist:
        await update.message.reply_text("❌ Vorlage nicht mehr vorhanden.")
        return ConversationHandler.END

    new_value = update.message.text

    if field_name in ("pickup_time", "return_time"):
        if new_value == "/skip" and field_name == "return_time":
            setattr(template, field_name, None)
        elif new_value and new_value != "/skip":
            try:
                hour, minute = new_value.strip().split(":")
                setattr(template, field_name, dtime(int(hour), int(minute)))
            except (ValueError, TypeError):
                await update.message.reply_text(
                    "⚠️ Ungültiges Format. Bitte HH:MM eingeben:"
                )
                return TEMPLATE_EDIT_NEW_VALUE
    elif field_name == "vehicle_type":
        if new_value and new_value in ("Sitz", "Liege", "Rad", "KTW"):
            setattr(template, field_name, new_value)
        else:
            await update.message.reply_text(
                "⚠️ Ungültiger Typ. Bitte Sitz, Liege, Rad oder KTW eingeben:"
            )
            return TEMPLATE_EDIT_NEW_VALUE
    else:
        if new_value and new_value != "/skip":
            setattr(template, field_name, new_value)

    await template.save()
    logger.info("Template updated: id=%d, field=%s", template_id, field_name)

    await update.message.reply_text(
        f"✅ *Feld aktualisiert!*\n\n{_format_template(template)}",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


async def vorlage_edit_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel template editing."""
    if update.message:
        await update.message.reply_text("❌ Bearbeitung abgebrochen.")
    return ConversationHandler.END


# ── NLU Booking Handler ──────────────────────────────────────────────────

# Minimum confidence threshold for accepting an NLU intent as valid
_MIN_CONFIDENCE = 0.40


async def handle_booking_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Process a free-text message as a potential booking request.

    Routes the message through DeepSeek NLU to extract booking intent and
    entities. Handles the complete booking flow:

    - ``book``: Create one-way or round-trip (with return) in the DB.
    - ``info``: Show upcoming trips / answer questions.
    - ``other``: Redirect to helpful commands.
    - Low confidence / unparseable: Ask patient to rephrase.
    - Unregistered patient: Guide to /start.
    - API failure: Graceful error message.

    This handler processes ALL non-command text messages from patients.
    """
    if update.effective_user is None or update.message is None:
        return

    telegram_id = update.effective_user.id
    text = update.message.text or ""

    if not text.strip():
        return

    # 1. Check patient is registered
    patient = await Patient.filter(telegram_id=telegram_id).first()
    if patient is None:
        await update.message.reply_text(
            "👋 Du bist noch nicht registriert! Bitte nutze /start, "
            "um dein Profil anzulegen. Danach kannst du Fahrten buchen."
        )
        return

    # 2. Run NLU extraction
    try:
        intent = await extract_booking_intent(text)
    except Exception as e:
        logger.exception("NLU extraction failed for patient %d: %s", telegram_id, e)
        await update.message.reply_text(
            "❌ Entschuldigung, ich kann deine Nachricht gerade nicht "
            "verarbeiten. Bitte versuche es später noch einmal oder "
            "rufe uns an."
        )
        return

    action = intent.action
    confidence = intent.confidence

    # 3. Route based on intent action
    if confidence < _MIN_CONFIDENCE:
        await _ask_to_rephrase(update)
        return

    if action == "book":
        await _handle_book_intent(update, patient, intent)
    elif action == "info":
        await _handle_info_intent(update, patient)
    elif action in ("recurring", "cancel", "change"):
        await update.message.reply_text(
            "ℹ️ Diese Funktion ist noch nicht verfügbar. "
            "Bitte kontaktiere unseren Support für "
            f"{_action_label(action)}."
        )
    else:  # other / anything else
        await _handle_other_intent(update, patient)


async def _ask_to_rephrase(update: Update) -> None:
    """Ask the patient to rephrase — NLU couldn't understand."""
    await update.message.reply_text(  # type: ignore[union-attr]
        "🤔 Das habe ich nicht richtig verstanden. "
        "Kannst du es anders formulieren?\n\n"
        "💡 *Beispiele:*\n"
        "• \"Morgen 8 Uhr zur Dialyse Klinikum Nord\"\n"
        "• \"Nächsten Dienstag 14:00 Physio Zentrum\"\n"
        "• \"Jeden Mo/Mi/Fr 9:00 Arztpraxis Dr. Müller\"\n\n"
        "Wichtig: Nenne Datum/Zeit, Ziel und ggf. Rückfahrtzeit.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _try_auto_dispatch(trip, update: Update) -> None:
    """Try to auto-assign a driver to a newly created trip."""
    from krankenfahrt.core.dispatch import GreedyDispatchEngine
    from krankenfahrt.models.schema import Driver

    drivers = await Driver.filter(active=True).all()
    if not drivers:
        logger.info("No active drivers for auto-dispatch of trip %d", trip.id)
        return

    engine = GreedyDispatchEngine()
    assignment = await engine.find_best_driver(trip, drivers)

    if assignment.driver is None:
        logger.info("No suitable driver found for trip %d", trip.id)
        return

    # Assign driver
    trip.driver = assignment.driver
    trip.status = "zugewiesen"
    await trip.save()

    # Log the assignment
    from krankenfahrt.models.schema import TripEvent
    await TripEvent.create(
        trip_id=trip.id,
        event_type="assigned",
        message=f"Auto-assigned to {assignment.driver.name} (score={assignment.score:.2f})",
    )

    # Notify driver
    try:
        await update.get_bot().send_message(
            chat_id=assignment.driver.telegram_id,
            text=(
                f"📋 *Neue Fahrt zugewiesen!*\n\n"
                f"👤 {trip.patient.name if await trip.patient else '?'}\n"
                f"📍 {trip.pickup_addr} → {trip.dest_addr}\n"
                f"🕐 {trip.scheduled_pickup.strftime('%d.%m.%Y %H:%M')}\n\n"
                f"Nutze /heute für deine Fahrten."
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        logger.warning("Failed to notify driver %d", assignment.driver.telegram_id)

    logger.info(
        "Auto-dispatched trip %d to driver %s (score=%.2f)",
        trip.id, assignment.driver.name, assignment.score,
    )


async def _handle_book_intent(
    update: Update, patient: Patient, intent
) -> None:
    """Create a trip (or trips) from a booking intent.

    Validates required fields, creates Trip records, and sends confirmation.
    """
    # Validate required fields
    if not intent.pickup_date or not intent.pickup_time:
        await update.message.reply_text(  # type: ignore[union-attr]
            "📅 *Wann soll die Fahrt stattfinden?*\n\n"
            "Bitte nenne Datum und Uhrzeit, z.B.:\n"
            "\"Morgen 8 Uhr\" oder \"Freitag 14:30\"",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if not intent.dest:
        await update.message.reply_text(  # type: ignore[union-attr]
            "📍 *Wohin soll die Fahrt gehen?*\n\n"
            "Bitte nenne das Ziel, z.B.:\n"
            "\"Klinikum Nord\", \"Physio Zentrum\", \"Arztpraxis Dr. Müller\"",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Parse date and time
    try:
        from datetime import datetime as dt
        pickup_dt = dt.fromisoformat(
            f"{intent.pickup_date}T{intent.pickup_time}:00"
        )
    except (ValueError, TypeError):
        await update.message.reply_text(  # type: ignore[union-attr]
            "❌ Datum oder Uhrzeit konnte nicht verstanden werden. "
            "Bitte formatiere so: \"Morgen 8 Uhr\" oder \"10.06.2026 14:30\"."
        )
        return

    pickup_addr = patient.default_pickup_addr

    # Create outbound trip
    trip = await Trip.create(
        patient=patient,
        pickup_addr=pickup_addr,
        dest_addr=intent.dest,
        scheduled_pickup=pickup_dt,
        status="geplant",
    )
    logger.info(
        "Trip booked: id=%d patient=%d dest=%s pickup=%s",
        trip.id, patient.id, intent.dest, pickup_dt.isoformat(),
    )

    # Create return trip if requested
    return_trip = None
    if intent.return_time:
        try:
            return_dt = dt.fromisoformat(
                f"{intent.pickup_date}T{intent.return_time}:00"
            )
            return_trip = await Trip.create(
                patient=patient,
                pickup_addr=intent.dest,
                dest_addr=pickup_addr,
                scheduled_pickup=return_dt,
                status="geplant",
            )
            logger.info(
                "Return trip booked: id=%d outbound=%d",
                return_trip.id, trip.id,
            )
        except (ValueError, TypeError):
            logger.warning("Could not parse return time: %s", intent.return_time)

    # Build and send confirmation
    from krankenfahrt.core.notification import Messages

    # Format pickup date+time nicely
    days_de = {
        "Mon": "Mo", "Tue": "Di", "Wed": "Mi",
        "Thu": "Do", "Fri": "Fr", "Sat": "Sa", "Sun": "So",
    }
    dow_en = pickup_dt.strftime("%a")
    dow_de = days_de.get(dow_en, dow_en)

    date_str = f"{dow_de} {pickup_dt.strftime('%d.%m.%Y')}"

    confirm_msg = (
        f"✅ *Fahrt gebucht!*\n\n"
        f"📅 {date_str} um {intent.pickup_time} Uhr\n"
        f"📍 Von: {pickup_addr}\n"
        f"🏥 Nach: {intent.dest}\n"
        f"🚗 Fahrzeugtyp: {patient.vehicle_type}\n"
    )

    if intent.return_time:
        confirm_msg += f"🔄 Rückfahrt: {intent.return_time} Uhr\n"
    if intent.reason:
        confirm_msg += f"📋 Grund: {intent.reason}\n"

    confirm_msg += (
        f"\n📞 Bei Fragen: {config.COMPANY_PHONE}\n\n"
        f"Wir melden uns, sobald ein Fahrer zugeteilt ist. "
        f"Du bekommst dann Name und Kennzeichen des Fahrers."
    )

    await update.message.reply_text(  # type: ignore[union-attr]
        confirm_msg,
        parse_mode=ParseMode.MARKDOWN,
    )

    # Auto-dispatch: try to assign a driver immediately
    try:
        await _try_auto_dispatch(trip, update)
    except Exception:
        logger.warning("Auto-dispatch failed for trip %d", trip.id, exc_info=True)


async def _handle_info_intent(update: Update, patient: Patient) -> None:
    """Show upcoming trips for the patient."""
    from datetime import datetime as dt

    now = dt.now()
    trips = await Trip.filter(
        patient=patient,
        scheduled_pickup__gte=now,
    ).order_by("scheduled_pickup").limit(5)

    if not trips:
        await update.message.reply_text(  # type: ignore[union-attr]
            "📋 Du hast aktuell keine anstehenden Fahrten.\n\n"
            "Schreib mir einfach wann und wohin du fahren möchtest, "
            "z.B.: \"Morgen 8 Uhr zur Dialyse Klinikum Nord\""
        )
        return

    lines = ["📋 *Deine nächsten Fahrten:*\n"]
    for t in trips:
        status_icon = {
            "geplant": "📋", "zugewiesen": "✅", "anfahrt": "🚗",
            "angekommen": "📍", "patient_an_bord": "👤",
            "unterwegs": "🏥", "abgesetzt": "✅", "abgeschlossen": "🔒",
        }.get(t.status, "❓")

        lines.append(
            f"{status_icon} {t.scheduled_pickup.strftime('%d.%m.%Y %H:%M')} → "
            f"{t.dest_addr} ({t.status})"
        )

    await update.message.reply_text(  # type: ignore[union-attr]
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


async def _handle_other_intent(update: Update, patient: Patient) -> None:
    """Redirect non-booking messages to helpful commands."""
    await update.message.reply_text(  # type: ignore[union-attr]
        "ℹ️ Ich bin dein Buchungsassistent für Krankentransporte.\n\n"
        "📋 Das kannst du tun:\n"
        "• Fahrten buchen: Einfach Nachricht schreiben!\n"
        "  z.B.: \"Morgen 8 Uhr zur Dialyse Klinikum Nord\"\n"
        "• /profil — Deine Daten anzeigen\n"
        "• /profil_edit — Profil bearbeiten\n"
        "• /vorlagen — Wiederkehrende Fahrten\n"
        "• Fahrten abfragen: \"Habe ich morgen eine Fahrt?\"\n\n"
        f"📞 Bei dringenden Anliegen: {config.COMPANY_PHONE}",
    )


def _action_label(action: str) -> str:
    """Human-readable German label for NLU actions."""
    return {
        "recurring": "wiederkehrende Fahrten",
        "cancel": "Stornierungen",
        "change": "Änderungen",
    }.get(action, action)


# ── Handler registration ───────────────────────────────────────────────────

def register_handlers(app: Application) -> None:
    """Register all Patient-Bot command and conversation handlers."""
    # Simple commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("profil", cmd_profil))
    app.add_handler(CommandHandler("vorlagen", cmd_vorlagen))
    app.add_handler(CommandHandler("vorlage_show", cmd_vorlage_show))
    app.add_handler(CommandHandler("vorlage_del", cmd_vorlage_del))

    # Profile editing conversation
    profile_edit_conv = ConversationHandler(
        entry_points=[CommandHandler("profil_edit", profil_edit_start)],
        states={
            PROFILE_EDIT_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profil_edit_name),
            ],
            PROFILE_EDIT_PHONE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profil_edit_phone),
            ],
            PROFILE_EDIT_PICKUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profil_edit_pickup),
            ],
            PROFILE_EDIT_DEST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profil_edit_dest),
            ],
            PROFILE_EDIT_INSURANCE_PROVIDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profil_edit_insurance_provider),
            ],
            PROFILE_EDIT_INSURANCE_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profil_edit_insurance_number),
            ],
            PROFILE_EDIT_VEHICLE_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profil_edit_vehicle_type),
            ],
            PROFILE_EDIT_SPECIAL_NEEDS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profil_edit_special_needs),
            ],
            PROFILE_EDIT_NOTES: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profil_edit_notes),
            ],
        },
        fallbacks=[CommandHandler("cancel", profil_edit_cancel)],
    )
    app.add_handler(profile_edit_conv)

    # New template creation conversation
    template_new_conv = ConversationHandler(
        entry_points=[CommandHandler("vorlage_neu", vorlage_neu_start)],
        states={
            TEMPLATE_NEW_PICKUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vorlage_neu_pickup),
            ],
            TEMPLATE_NEW_DEST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vorlage_neu_dest),
            ],
            TEMPLATE_NEW_DAYS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vorlage_neu_days),
            ],
            TEMPLATE_NEW_PICKUP_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vorlage_neu_pickup_time),
            ],
            TEMPLATE_NEW_RETURN_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vorlage_neu_return_time),
            ],
            TEMPLATE_NEW_VEHICLE_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vorlage_neu_vehicle_type),
            ],
            TEMPLATE_NEW_CONFIRM: [
                CallbackQueryHandler(
                    callback_vorlage_neu_confirm,
                    pattern=r"^tpl_new_(confirm|cancel)$",
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", vorlage_neu_cancel)],
    )
    app.add_handler(template_new_conv)

    # Template editing conversation
    template_edit_conv = ConversationHandler(
        entry_points=[CommandHandler("vorlage_edit", vorlage_edit_start)],
        states={
            TEMPLATE_EDIT_SELECT_FIELD: [
                CallbackQueryHandler(
                    callback_tpl_edit_select,
                    pattern=r"^tpl_edit_",
                ),
            ],
            TEMPLATE_EDIT_NEW_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, vorlage_edit_new_value),
            ],
        },
        fallbacks=[CommandHandler("cancel", vorlage_edit_cancel)],
    )
    app.add_handler(template_edit_conv)

    # Delete confirmation callback
    app.add_handler(
        CallbackQueryHandler(
            callback_vorlage_del_confirm,
            pattern=r"^tpl_del_",
        )
    )

    logger.info(
        "Patient-Bot handlers registered: start, profil, profil_edit, "
        "vorlagen, vorlage_neu, vorlage_show, vorlage_edit, vorlage_del, "
        "booking_nlu"
    )

    # ── Free-text booking handler (NLU) ──────────────────────────────────
    # Processes ALL non-command text messages through DeepSeek NLU for
    # booking intent extraction. Placed LAST so conversation handlers
    # (profile_edit, vorlage_neu, vorlage_edit) take priority.
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_booking_message)
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Live Location Tracking & Status Push API
# ═══════════════════════════════════════════════════════════════════════════════
#
# These functions are called externally when a trip's state changes (from the
# state machine callbacks, driver bot, or dispatch engine). They push status
# notifications to the patient and manage the live location sharing lifecycle.
# ═══════════════════════════════════════════════════════════════════════════════

from krankenfahrt.services.live_location import LiveLocationTracker

# Module-level tracker — shared across the patient bot.
# In production this would be a dependency-injected service, but for MVP
# a singleton works since only one patient bot instance runs per process.
_live_tracker = LiveLocationTracker()


def get_live_tracker() -> LiveLocationTracker:
    """Return the module-level live location tracker instance."""
    return _live_tracker


# German display names for each trip state (used in push notifications).
STATUS_DISPLAY: dict[str, str] = {
    "geplant": "📋 Geplant — noch kein Fahrer zugewiesen",
    "zugewiesen": "✅ Fahrer zugewiesen",
    "anfahrt": "🚗 Ihr Fahrer ist unterwegs zu Ihnen",
    "angekommen": "📍 Fahrer ist angekommen — bitte kommen Sie zur Abholung",
    "patient_an_bord": "👤 Sie sind an Bord",
    "unterwegs": "🏥 Unterwegs zum Ziel",
    "abgesetzt": "✅ Sie wurden abgesetzt",
    "abgeschlossen": "🔒 Fahrt abgeschlossen",
    "storniert": "❌ Fahrt storniert",
    "problem": "⚠️ Es gibt ein Problem mit Ihrer Fahrt",
}


def _format_status_message(status: str, **ctx: str) -> str:
    """Build a human-readable status message in German.

    Args:
        status: The trip state machine status (e.g., "anfahrt").
        **ctx: Optional context values for message formatting
               (driver_name, pickup_time, dest_addr, etc.).
    """
    base = STATUS_DISPLAY.get(status, f"ℹ️ Status: {status}")

    if status == "anfahrt" and "driver_name" in ctx:
        base += f"\n👋 Fahrer: {ctx['driver_name']}"
    if status == "abgesetzt" and "time" in ctx:
        base += f"\n🕐 Zeit: {ctx['time']}"

    return base


async def push_status_update(
        app: Application,
        chat_id: int,
        status: str,
        **ctx: str,
    ) -> int | None:
    """Push a status update notification to a patient.

    This is the primary entry point for notifying patients about trip
    state changes. Sends a text message via Telegram.

    Args:
        app: The patient bot's Application instance.
        chat_id: Patient's Telegram chat ID.
        status: New trip status (from TRIP_STATES).
        **ctx: Context for message formatting (driver_name, etc.).

    Returns:
        The sent message ID or None on failure.
    """
    if not app.bot:
        logger.error("push_status_update called before bot initialization")
        return None

    text = _format_status_message(status, **ctx)

    try:
        message = await app.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
        logger.info(
            "Status push sent: chat=%d status=%s msg=%d",
            chat_id, status, message.message_id,
        )
        return message.message_id
    except TelegramError as e:
        logger.error(
            "Failed to push status update to chat %d: %s", chat_id, e,
        )
        return None


async def start_live_tracking(
    app: Application,
    trip_id: int,
    chat_id: int,
    lat: float,
    lon: float,
    driver_name: str = "",
) -> bool:
    """Start live location tracking for a trip.

    Sends the initial location message that Telegram displays as a
    live-updating blue dot. The returned message_id is stored so
    subsequent position updates can edit the same message.

    Args:
        app: Patient bot Application instance.
        trip_id: Database trip ID (used as session key).
        chat_id: Patient's Telegram chat ID.
        lat, lon: Initial driver GPS position.
        driver_name: Driver name for the status message prefix.

    Returns:
        True if live location was started successfully.
    """
    if not app.bot:
        logger.error("start_live_tracking called before bot initialization")
        return False

    tracker = get_live_tracker()

    # Send a text status message first with driver info
    if driver_name:
        await push_status_update(app, chat_id, "anfahrt", driver_name=driver_name)

    # Start the live location message
    result = await tracker.start(
        bot=app.bot,
        trip_id=trip_id,
        chat_id=chat_id,
        lat=lat,
        lon=lon,
    )

    if result is not None:
        logger.info(
            "Live tracking started: trip=%d chat=%d msg=%d",
            trip_id, chat_id, result,
        )
        return True
    return False


async def update_live_tracking(
    app: Application,
    trip_id: int,
    lat: float,
    lon: float,
) -> bool:
    """Update the driver's live location on the patient's map.

    Edits the existing live location message rather than sending a new
    one — Telegram UI shows the blue dot moving smoothly.

    Args:
        app: Patient bot Application instance.
        trip_id: Database trip ID.
        lat, lon: Updated driver GPS position.

    Returns:
        True if the location update was sent successfully.
    """
    if not app.bot:
        return False
    tracker = get_live_tracker()
    return await tracker.update(bot=app.bot, trip_id=trip_id, lat=lat, lon=lon)


async def stop_live_tracking(
    app: Application,
    trip_id: int,
    chat_id: int,
    arrived: bool = True,
) -> bool:
    """Stop live location sharing for a trip.

    Args:
        app: Patient bot Application instance.
        trip_id: Database trip ID.
        chat_id: Patient's chat ID (for the arrival notification).
        arrived: If True, send an "arrived" status notification to the patient.

    Returns:
        True if live location was stopped successfully.
    """
    if not app.bot:
        return False

    tracker = get_live_tracker()

    # Stop the live location message
    stopped = await tracker.stop(bot=app.bot, trip_id=trip_id)

    # Send a final status notification
    if arrived:
        await push_status_update(app, chat_id, "angekommen")

    return stopped


# ═══════════════════════════════════════════════════════════════════════════
# State-change decision helpers
# ═══════════════════════════════════════════════════════════════════════════
#
# These pure functions determine what actions to take when a trip state
# changes. They are separated from the push functions so they can be
# tested without Telegram bot infrastructure.
# ═══════════════════════════════════════════════════════════════════════════

# States that should trigger live location start.
_LOCATION_START_STATES: set[str] = {"anfahrt"}

# States that should trigger live location stop.
_LOCATION_STOP_STATES: set[str] = {
    "angekommen", "abgesetzt", "abgeschlossen", "storniert",
}

# States that should trigger a patient text notification.
_NOTIFY_STATES: set[str] = {
    "zugewiesen", "anfahrt", "angekommen", "patient_an_bord",
    "unterwegs", "abgesetzt", "abgeschlossen", "storniert", "problem",
}


def should_start_live_location(new_status: str) -> bool:
    """Return True if this state transition should start live location."""
    return new_status in _LOCATION_START_STATES


def should_stop_live_location(new_status: str) -> bool:
    """Return True if this state transition should stop live location."""
    return new_status in _LOCATION_STOP_STATES


def should_notify_patient(new_status: str) -> bool:
    """Return True if this state change should push a patient notification."""
    return new_status in _NOTIFY_STATES
