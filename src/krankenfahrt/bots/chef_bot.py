"""Chef-Bot (@FahrtenChef): Dispatcher/Owner interface.

Commands:
  /start      — Show available commands
  /dashboard  — Daily overview of all trips
  /export     — Export billing data (CSV or Muster-4 PDF invoice)
  /fahrer     — Driver management (create, list, update, delete)
  /fahrzeug   — Vehicle management (create, list, update, delete)
"""

from __future__ import annotations

import functools
from datetime import date, datetime, timedelta
from typing import Callable, Coroutine

import structlog
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from krankenfahrt.config import PROJECT_ROOT, config
from krankenfahrt.models.schema import Driver, Patient, Vehicle
from krankenfahrt.resilience.db_retry import db_retry
from krankenfahrt.services.billing import (
    ExportFilters,
    export_billing_csv,
    generate_invoice_for_trips,
)

logger = structlog.get_logger(__name__)


# =============================================================================
# Auth decorator
# =============================================================================


def _require_admin(
    handler: Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine],
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine]:
    """Decorator: only allow users whose Telegram ID is in ADMIN_TELEGRAM_IDS."""

    @functools.wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id
        if user_id not in config.ADMIN_TELEGRAM_IDS:
            await update.message.reply_text(
                "⛔ *Keine Berechtigung.*\n"
                "Dieser Befehl ist nur für autorisierte Disponenten verfügbar.",
                parse_mode="Markdown",
            )
            logger.warning("Unauthorized access attempt", user_id=user_id)
            return
        return await handler(update, context)

    return wrapper


# =============================================================================
# Helpers
# =============================================================================


def _parse_date_arg(text: str) -> date | None:
    """Parse a date in DD.MM.YYYY or YYYY-MM-DD format."""
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_int_arg(text: str) -> int | None:
    """Parse an integer argument, returning None on failure."""
    try:
        return int(text.strip())
    except (ValueError, TypeError):
        return None


def _format_driver(d: Driver) -> str:
    """Format a single driver for display."""
    status = "✅ aktiv" if d.active else "❌ inaktiv"
    p_schein = "✅ P-Schein" if d.p_schein else "⛔ kein P-Schein"
    vehicle_info = ""
    # We can't await here — handled in list handlers
    return (
        f"*ID {d.id}* — {d.name}\n"
        f"  📞 {d.phone}  |  {status}  |  {p_schein}\n"
        f"  🕐 {d.work_hours_start}–{d.work_hours_end}  |  📅 {d.work_days}"
    )


def _format_vehicle(v: Vehicle) -> str:
    """Format a single vehicle for display."""
    return (
        f"*ID {v.id}* — {v.license_plate}\n"
        f"  🚗 Typ: {v.vehicle_type}  |  🧑 Kapazität: {v.capacity}"
        + (f"\n  📝 {v.notes}" if v.notes else "")
    )


# =============================================================================
# /start
# =============================================================================


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start message with available commands."""
    await update.message.reply_text(
        "🚑 *FahrtenChef* — Dein Disponenten-Cockpit\n\n"
        "Verfügbare Befehle:\n"
        "/dashboard — Heutige Fahrten im Überblick\n"
        "/export csv \\[von] \\[bis] — Abrechnungs-CSV exportieren\n"
        "  z.B. `/export csv 01.06.2026 30.06.2026`\n"
        "/export pdf <Patient-ID> \\[von] \\[bis] — Muster-4 PDF-Rechnung\n"
        "  z.B. `/export pdf 1 01.06.2026 30.06.2026`\n"
        "/fahrer — Fahrerverwaltung\n"
        "/fahrzeug — Fahrzeugverwaltung",
        parse_mode="Markdown",
    )


# =============================================================================
# =============================================================================
# /export
# =============================================================================

EXPORT_HELP = (
    "\U0001f4ca *Abrechnungs-Export*\n\n"
    "*CSV-Export:*\n"
    "`/export csv [von] [bis]`\n"
    "  Ohne Datum: Alle Fahrten exportieren.\n"
    "  Mit einem Datum: ab diesem Datum.\n"
    "  Mit zwei Daten: Zeitraum von\u2013bis.\n\n"
    "*PDF-Rechnung (Muster-4):*\n"
    "`/export pdf <Patient-ID> [von] [bis]`\n"
    "  Erzeugt eine Muster-4 PDF-Rechnung f\u00fcr den Patienten.\n"
    "  Optionale Datumsangaben grenzen den Zeitraum ein.\n\n"
    "*Beispiele:*\n"
    "`/export csv 01.06.2026 30.06.2026`\n"
    "`/export pdf 1 01.06.2026 30.06.2026`"
)


@_require_admin
async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Router for /export subcommands.

    Usage:
      /export csv [from] [to]   \u2014 CSV export
      /export pdf <patient_id> [from] [to]  \u2014 PDF Muster-4 invoice
      /export                    \u2014 show help
    """
    args = context.args

    if not args:
        await update.message.reply_text(EXPORT_HELP, parse_mode="Markdown")
        return

    sub = args[0].lower()

    if sub == "csv":
        await _handle_export_csv(update, context)
    elif sub == "pdf":
        await _handle_export_pdf(update, context)
    else:
        # Backward compatibility: if first arg looks like a date, treat as CSV
        if _parse_date_arg(args[0]) is not None:
            await _handle_export_csv(update, context)
        else:
            await update.message.reply_text(
                f"\u2753 Unbekannter Unterbefehl: `{sub}`\n\n{EXPORT_HELP}",
                parse_mode="Markdown",
            )


async def _handle_export_csv(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """CSV export of billing data.

    Usage: /export csv [from] [to]
    Without args: export all trips.
    With one date: from that date onward.
    With two dates: range from\u2013to.
    """
    args = context.args
    # Skip "csv" subcommand if present
    if args and args[0].lower() == "csv":
        args = args[1:]
    filters = ExportFilters()

    if len(args) >= 1:
        date_from = _parse_date_arg(args[0])
        if date_from is None:
            await update.message.reply_text(
                "\u274c Ung\u00fcltiges Datum. Bitte im Format DD.MM.YYYY angeben, "
                "z.B. `/export csv 01.06.2026`",
                parse_mode="Markdown",
            )
            return
        filters.date_from = date_from

    if len(args) >= 2:
        date_to = _parse_date_arg(args[1])
        if date_to is None:
            await update.message.reply_text(
                "\u274c Ung\u00fcltiges Enddatum. Bitte im Format DD.MM.YYYY angeben.",
                parse_mode="Markdown",
            )
            return
        filters.date_to = date_to

    await update.message.reply_text(
        "\u23f3 Exportiere Abrechnungsdaten..."
        + (
            "\nZeitraum: "
            + filters.date_from.strftime("%d.%m.%Y")
            + " \u2013 "
            + filters.date_to.strftime("%d.%m.%Y")
            if filters.date_from
            else ""
        ),
    )

    try:
        filepath = await export_billing_csv(filters=filters)
        with open(filepath, "rb") as f:
            caption_text = (
                "\U0001f4ca Abrechnungs-Export\n"
                "Alle Fahrten\n"
                f"Datei: `{filepath.name}`"
            )
            if filters.date_from:
                caption_text = (
                    "\U0001f4ca Abrechnungs-Export\n"
                    f"Zeitraum: {filters.date_from.strftime('%d.%m.%Y')} \u2013 "
                    f"{filters.date_to.strftime('%d.%m.%Y')}\n"
                    f"Datei: `{filepath.name}`"
                )
            await update.message.reply_document(
                document=f,
                filename=filepath.name,
                caption=caption_text,
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.exception("CSV export failed")
        await update.message.reply_text(f"\u274c Export fehlgeschlagen: {e}")


async def _handle_export_pdf(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Generate Muster-4 PDF invoice for a specific patient.

    Usage: /export pdf <patient_id> [from] [to]
    """
    args = context.args
    # Skip "pdf" subcommand
    if args and args[0].lower() == "pdf":
        args = args[1:]

    if not args:
        await update.message.reply_text(
            "\u274c Bitte eine Patient-ID angeben.\n\n"
            "Verwendung: `/export pdf <Patient-ID> [von] [bis]`\n\n"
            "Beispiel: `/export pdf 1 01.06.2026 30.06.2026`",
            parse_mode="Markdown",
        )
        return

    patient_id = _parse_int_arg(args[0])
    if patient_id is None:
        await update.message.reply_text(
            f"\u274c Ung\u00fcltige Patient-ID: `{args[0]}`. Bitte eine Zahl angeben.",
            parse_mode="Markdown",
        )
        return

    # Fetch patient
    patient = await Patient.filter(id=patient_id).first()
    if patient is None:
        await update.message.reply_text(
            f"\u274c Patient mit ID *{patient_id}* nicht gefunden.",
            parse_mode="Markdown",
        )
        return

    # Parse optional date filters
    date_from = None
    date_to = None
    date_args = args[1:]

    if len(date_args) >= 1:
        date_from = _parse_date_arg(date_args[0])
        if date_from is None:
            await update.message.reply_text(
                "\u274c Ung\u00fcltiges Von-Datum. Bitte im Format DD.MM.YYYY angeben.",
                parse_mode="Markdown",
            )
            return

    if len(date_args) >= 2:
        date_to = _parse_date_arg(date_args[1])
        if date_to is None:
            await update.message.reply_text(
                "\u274c Ung\u00fcltiges Bis-Datum. Bitte im Format DD.MM.YYYY angeben.",
                parse_mode="Markdown",
            )
            return

    await update.message.reply_text(
        "\u23f3 Erstelle Muster-4 Rechnung..."
        + (f"\nPatient: {patient.name}" if patient.name else ""),
    )

    try:
        from krankenfahrt.models.schema import Trip as TripModel
        from krankenfahrt.services.billing import generate_invoice_for_trips

        # Query trips for this patient, filtered by date range if provided
        query = (
            TripModel.filter(patient_id=patient_id)
            .prefetch_related("vehicle", "patient")
        )

        if date_from:
            query = query.filter(scheduled_pickup__gte=date_from)
        if date_to:
            query = query.filter(scheduled_pickup__lte=date_to)

        trips = await query

        if not trips:
            await update.message.reply_text(
                "\u26a0\ufe0f Keine Fahrten f\u00fcr diesen Patienten im angegebenen Zeitraum gefunden.",
            )
            return

        # Generate the invoice
        output_dir = PROJECT_ROOT / "data" / "exports"
        output_dir.mkdir(parents=True, exist_ok=True)

        pdf_path = await generate_invoice_for_trips(
            trips=trips,
            patient_name=patient.name,
            patient_geburtsdatum="",
            patient_strasse=patient.default_pickup_addr or "",
            patient_ort="",
            patient_versichertennummer=patient.insurance_number or "",
            kk_name=patient.insurance_provider or "Krankenkasse",
            kk_strasse="",
            kk_ort="",
            kk_ik_nummer="",
            output_dir=output_dir,
        )

        with open(pdf_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=pdf_path.name,
                caption=(
                    f"\U0001f4c4 Muster-4 Rechnung\n"
                    f"Patient: {patient.name}\n"
                    f"Fahrten: {len(trips)}\n"
                    f"Datei: `{pdf_path.name}`"
                ),
                parse_mode="Markdown",
            )

    except Exception as e:
        logger.exception("PDF export failed")
        await update.message.reply_text(f"\u274c PDF-Export fehlgeschlagen: {e}")


# /fahrer — Driver Management
# =============================================================================


FAHRER_HELP = (
    "👨‍✈️ *Fahrerverwaltung*\n\n"
    "*Befehle:*\n"
    "`/fahrer add <Vorname> <Nachname> <Telefon>` — Fahrer anlegen\n"
    "`/fahrer list` — Alle Fahrer anzeigen\n"
    "`/fahrer list-active` — Nur aktive Fahrer\n"
    "`/fahrer update <ID> name <Vorname> <Nachname>` — Name ändern\n"
    "`/fahrer update <ID> phone <Telefon>` — Telefon ändern\n"
    "`/fahrer update <ID> activate` — Fahrer aktivieren\n"
    "`/fahrer update <ID> deactivate` — Fahrer deaktivieren\n"
    "`/fahrer update <ID> pschein <ja|nein>` — P-Schein Status\n"
    "`/fahrer delete <ID>` — Fahrer löschen (Bestätigung erforderlich)\n"
    "`/fahrer delete <ID> confirm` — Löschung bestätigen\n"
    "\n*Beispiele:*\n"
    "`/fahrer add Max Mustermann 017612345678`\n"
    "`/fahrer update 3 name Erika Mustermann`"
)


@_require_admin
async def cmd_fahrer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Router for /fahrer subcommands."""
    args = context.args

    if not args:
        await update.message.reply_text(FAHRER_HELP, parse_mode="Markdown")
        return

    sub = args[0].lower()

    if sub == "add":
        await _handle_driver_add(update, context)
    elif sub in ("list", "liste", "show", "all", "alle"):
        await _handle_driver_list(update, context, active_only=False)
    elif sub in ("list-active", "active"):
        await _handle_driver_list(update, context, active_only=True)
    elif sub in ("update", "edit", "ändern"):
        await _handle_driver_update(update, context)
    elif sub in ("delete", "remove", "löschen"):
        await _handle_driver_delete(update, context)
    else:
        await update.message.reply_text(
            f"❓ Unbekannter Unterbefehl: `{sub}`\n\n{FAHRER_HELP}",
            parse_mode="Markdown",
        )


async def _handle_driver_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create a new driver.

    Usage: /fahrer add <Vorname> <Nachname> <Telefon> [Telegram-ID]
    """
    args = context.args[1:]  # Skip "add"

    if len(args) < 3:
        await update.message.reply_text(
            "❌ *Unzureichende Argumente.*\n\n"
            "Verwendung: `/fahrer add <Vorname> <Nachname> <Telefon> [Telegram-ID]`\n\n"
            "Beispiel: `/fahrer add Max Mustermann 017612345678 123456789`\n"
            "_(Die Telegram-ID ist optional. Ohne sie kann der Fahrer den Bot nicht nutzen.)_",
            parse_mode="Markdown",
        )
        return

    # Parse: last arg is phone, second-to-last (if numeric and 8+ digits) is telegram_id
    # Only attempt telegram_id extraction when we have 4+ args (name parts + phone + optional id)
    # Strip markdown formatting characters (*, _, ~, `) that users may accidentally include
    args = [a.strip("*_~`") for a in args]

    telegram_id = 0
    if len(args) >= 4 and args[-1].isdigit() and len(args[-1]) >= 8:
        telegram_id = int(args[-1])
        args = args[:-1]  # Remove telegram_id from args
    *name_parts, phone = args
    name = " ".join(name_parts)

    # Check for duplicates
    existing = await Driver.filter(name__iexact=name).first()
    if existing:
        await update.message.reply_text(
            f"⚠️ Ein Fahrer mit dem Namen *{name}* existiert bereits (ID {existing.id}).\n"
            f"Verwende `/fahrer list` um alle Fahrer zu sehen.",
            parse_mode="Markdown",
        )
        return

    try:
        driver = await db_retry(
            lambda: Driver.create(
                telegram_id=telegram_id,
                name=name,
                phone=phone,
                active=True,
            ),
            operation_name="driver_create",
        )
        logger.info("Driver created", driver_id=driver.id, name=name)

        await update.message.reply_text(
            f"✅ *Fahrer angelegt!*\n\n"
            f"*ID {driver.id}* — {driver.name}\n"
            f"📞 {driver.phone}\n"
            f"Status: aktiv\n\n"
            f"Tipp: Mit `/fahrer update {driver.id} pschein ja` "
            f"kannst du den Personenbeförderungsschein hinterlegen.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception("Failed to create driver")
        await update.message.reply_text(f"❌ Fehler beim Anlegen: {e}")


async def _handle_driver_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE, active_only: bool = False
) -> None:
    """List drivers, optionally filtered by active status."""
    if active_only:
        drivers = await Driver.filter(active=True).all()
        title = "👨‍✈️ *Aktive Fahrer*"
    else:
        drivers = await Driver.all()
        title = "👨‍✈️ *Alle Fahrer*"

    if not drivers:
        await update.message.reply_text(
            f"{title}\n\n_Keine Fahrer vorhanden._",
            parse_mode="Markdown",
        )
        return

    lines = [title, ""]
    for d in drivers:
        lines.append(_format_driver(d))
        lines.append("")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


async def _handle_driver_update(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Update a driver's details.

    Usage:
      /fahrer update <ID> name <Vorname> <Nachname>
      /fahrer update <ID> phone <Telefon>
      /fahrer update <ID> activate
      /fahrer update <ID> deactivate
      /fahrer update <ID> pschein <ja|nein>
    """
    args = context.args[1:]  # Skip "update"

    if len(args) < 2:
        await update.message.reply_text(
            "❌ *Unzureichende Argumente.*\n\n"
            "Verwendung:\n"
            "`/fahrer update <ID> name <Vorname> <Nachname>`\n"
            "`/fahrer update <ID> phone <Telefon>`\n"
            "`/fahrer update <ID> activate|deactivate`\n"
            "`/fahrer update <ID> pschein <ja|nein>`",
            parse_mode="Markdown",
        )
        return

    driver_id = _parse_int_arg(args[0])
    if driver_id is None:
        await update.message.reply_text(
            f"❌ Ungültige ID: `{args[0]}`. Bitte eine Zahl angeben.",
            parse_mode="Markdown",
        )
        return

    driver = await Driver.filter(id=driver_id).first()
    if driver is None:
        await update.message.reply_text(
            f"❌ Fahrer mit ID *{driver_id}* nicht gefunden.\n"
            f"Verwende `/fahrer list` um alle IDs zu sehen.",
            parse_mode="Markdown",
        )
        return

    field = args[1].lower()

    if field == "name":
        if len(args) < 4:
            await update.message.reply_text(
                "❌ Bitte Vor- und Nachnamen angeben.\n"
                "Beispiel: `/fahrer update 1 name Erika Mustermann`",
                parse_mode="Markdown",
            )
            return
        new_name = " ".join(args[2:])
        old_name = driver.name
        driver.name = new_name
        await db_retry(lambda: driver.save(), operation_name="driver_save_name")
        await update.message.reply_text(
            f"✅ Fahrer *{old_name}* umbenannt zu *{new_name}*.",
            parse_mode="Markdown",
        )

    elif field == "phone":
        if len(args) < 3:
            await update.message.reply_text(
                "❌ Bitte die neue Telefonnummer angeben.\n"
                "Beispiel: `/fahrer update 1 phone 017699988877`",
                parse_mode="Markdown",
            )
            return
        new_phone = args[2]
        old_phone = driver.phone
        driver.phone = new_phone
        await db_retry(lambda: driver.save(), operation_name="driver_save_phone")
        await update.message.reply_text(
            f"✅ Telefon von *{driver.name}* aktualisiert:\n"
            f"`{old_phone}` → `{new_phone}`",
            parse_mode="Markdown",
        )

    elif field == "activate":
        driver.active = True
        await db_retry(lambda: driver.save(), operation_name="driver_save_activate")
        await update.message.reply_text(
            f"✅ Fahrer *{driver.name}* ist jetzt *aktiv*.",
            parse_mode="Markdown",
        )

    elif field == "deactivate":
        driver.active = False
        await db_retry(lambda: driver.save(), operation_name="driver_save_deactivate")
        await update.message.reply_text(
            f"✅ Fahrer *{driver.name}* wurde *deaktiviert*.",
            parse_mode="Markdown",
        )

    elif field == "pschein":
        if len(args) < 3:
            await update.message.reply_text(
                "❌ Bitte `ja` oder `nein` angeben.\n"
                "Beispiel: `/fahrer update 1 pschein ja`",
                parse_mode="Markdown",
            )
            return
        val = args[2].lower()
        if val in ("ja", "yes", "true", "1", "j"):
            driver.p_schein = True
            await update.message.reply_text(
                f"✅ P-Schein für *{driver.name}*: *vorhanden*.",
                parse_mode="Markdown",
            )
        elif val in ("nein", "no", "false", "0", "n"):
            driver.p_schein = False
            await update.message.reply_text(
                f"✅ P-Schein für *{driver.name}*: *nicht vorhanden*.",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                f"❌ Ungültiger Wert: `{val}`. Bitte `ja` oder `nein` angeben.",
                parse_mode="Markdown",
            )
            return
        await db_retry(lambda: driver.save(), operation_name="driver_save_pschein")

    else:
        await update.message.reply_text(
            f"❓ Unbekanntes Feld: `{field}`\n\n"
            "Verfügbare Felder: `name`, `phone`, `activate`, `deactivate`, `pschein`",
            parse_mode="Markdown",
        )


async def _handle_driver_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Delete a driver — requires explicit confirmation.

    Usage:
      /fahrer delete <ID>         → asks for confirmation
      /fahrer delete <ID> confirm → actually deletes (deactivates)
    """
    args = context.args[1:]  # Skip "delete"

    if len(args) < 1:
        await update.message.reply_text(
            "❌ Bitte die ID des Fahrers angeben.\n"
            "Beispiel: `/fahrer delete 3`",
            parse_mode="Markdown",
        )
        return

    driver_id = _parse_int_arg(args[0])
    if driver_id is None:
        await update.message.reply_text(
            f"❌ Ungültige ID: `{args[0]}`",
            parse_mode="Markdown",
        )
        return

    driver = await Driver.filter(id=driver_id).first()
    if driver is None:
        await update.message.reply_text(
            f"❌ Fahrer mit ID *{driver_id}* nicht gefunden.",
            parse_mode="Markdown",
        )
        return

    # Check if confirmation is provided
    confirmed = len(args) >= 2 and args[1].lower() == "confirm"

    if not confirmed:
        await update.message.reply_text(
            f"⚠️ *Wirklich löschen?*\n\n"
            f"Fahrer: *{driver.name}* (ID {driver.id})\n"
            f"Telefon: {driver.phone}\n\n"
            f"Zum Bestätigen: `/fahrer delete {driver.id} confirm`\n"
            f"Der Fahrer wird deaktiviert, vergangene Fahrten bleiben erhalten.",
            parse_mode="Markdown",
        )
        return

    # Soft-delete: deactivate rather than hard-delete to preserve trip history
    driver.active = False
    await db_retry(lambda: driver.save(), operation_name="driver_save_delete_deactivate")

    logger.info("Driver deactivated", driver_id=driver.id, name=driver.name)

    await update.message.reply_text(
        f"🗑️ Fahrer *{driver.name}* (ID {driver.id}) wurde *deaktiviert*.\n"
        f"Vergangene Fahrten bleiben in der Datenbank erhalten.",
        parse_mode="Markdown",
    )


# =============================================================================
# /fahrzeug — Vehicle Management
# =============================================================================


FAHRZEUG_HELP = (
    "🚗 *Fahrzeugverwaltung*\n\n"
    "*Befehle:*\n"
    "`/fahrzeug add <Marke> <Modell> <Kennzeichen> [Typ]` — Fahrzeug anlegen\n"
    "`/fahrzeug list` — Alle Fahrzeuge anzeigen\n"
    "`/fahrzeug update <ID> type <Typ>` — Fahrzeugtyp ändern (Sitz|Liege|Rad|KTW)\n"
    "`/fahrzeug update <ID> plate <Kennzeichen>` — Kennzeichen ändern\n"
    "`/fahrzeug update <ID> capacity <N>` — Kapazität ändern\n"
    "`/fahrzeug update <ID> notes <Text>` — Notiz aktualisieren\n"
    "`/fahrzeug delete <ID>` — Fahrzeug löschen (Bestätigung erforderlich)\n"
    "`/fahrzeug delete <ID> confirm` — Löschung bestätigen\n"
    "\n*Beispiele:*\n"
    "`/fahrzeug add VW Golf B-AB-1234`\n"
    "`/fahrzeug add Mercedes Sprinter B-XY-5678 KTW`\n"
    "`/fahrzeug update 2 type KTW`"
)


@_require_admin
async def cmd_fahrzeug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Router for /fahrzeug subcommands."""
    args = context.args

    if not args:
        await update.message.reply_text(FAHRZEUG_HELP, parse_mode="Markdown")
        return

    sub = args[0].lower()

    if sub == "add":
        await _handle_vehicle_add(update, context)
    elif sub in ("list", "liste", "show", "all", "alle"):
        await _handle_vehicle_list(update, context)
    elif sub in ("update", "edit", "ändern"):
        await _handle_vehicle_update(update, context)
    elif sub in ("delete", "remove", "löschen"):
        await _handle_vehicle_delete(update, context)
    else:
        await update.message.reply_text(
            f"❓ Unbekannter Unterbefehl: `{sub}`\n\n{FAHRZEUG_HELP}",
            parse_mode="Markdown",
        )


async def _handle_vehicle_add(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Create a new vehicle.

    Usage: /fahrzeug add <Marke> <Modell> <Kennzeichen> [Typ]
    """
    args = context.args[1:]  # Skip "add"

    if len(args) < 3:
        await update.message.reply_text(
            "❌ *Unzureichende Argumente.*\n\n"
            "Verwendung: `/fahrzeug add <Marke> <Modell> <Kennzeichen> [Typ]`\n\n"
            "Beispiele:\n"
            "`/fahrzeug add VW Golf B-AB-1234`\n"
            "`/fahrzeug add Mercedes Sprinter B-XY-5678 KTW`\n\n"
            "Typen: Sitz (Standard), Liege, Rad, KTW",
            parse_mode="Markdown",
        )
        return

    # Last required arg is license plate; optional vehicle type after that
    if len(args) >= 4 and args[3].upper() in ("SITZ", "LIEGE", "RAD", "KTW"):
        vehicle_type = args[3].upper()
        plate = args[2]
        make_model = " ".join(args[:2])
    else:
        vehicle_type = "Sitz"
        plate = args[2]
        make_model = " ".join(args[:2])

    # Check for duplicate plate
    existing = await Vehicle.filter(license_plate__iexact=plate).first()
    if existing:
        await update.message.reply_text(
            f"⚠️ Ein Fahrzeug mit dem Kennzeichen *{plate}* existiert bereits (ID {existing.id}).\n"
            f"Verwende `/fahrzeug list` um alle Fahrzeuge zu sehen.",
            parse_mode="Markdown",
        )
        return

    try:
        vehicle = await db_retry(
            lambda: Vehicle.create(
                license_plate=plate.upper(),
                vehicle_type=vehicle_type,
                capacity=1,
                notes=make_model,
            ),
            operation_name="vehicle_create",
        )
        logger.info("Vehicle created", vehicle_id=vehicle.id, plate=plate)

        await update.message.reply_text(
            f"✅ *Fahrzeug angelegt!*\n\n"
            f"*ID {vehicle.id}* — {make_model}\n"
            f"🚗 Kennzeichen: {vehicle.license_plate}\n"
            f"📦 Typ: {vehicle.vehicle_type}\n"
            f"🧑 Kapazität: {vehicle.capacity}\n\n"
            f"Tipp: Mit `/fahrzeug update {vehicle.id} type KTW` "
            f"kannst du den Typ ändern.",
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.exception("Failed to create vehicle")
        await update.message.reply_text(f"❌ Fehler beim Anlegen: {e}")


async def _handle_vehicle_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """List all vehicles."""
    vehicles = await Vehicle.all()

    if not vehicles:
        await update.message.reply_text(
            "🚗 *Alle Fahrzeuge*\n\n_Keine Fahrzeuge vorhanden._",
            parse_mode="Markdown",
        )
        return

    lines = ["🚗 *Alle Fahrzeuge*", ""]
    for v in vehicles:
        lines.append(_format_vehicle(v))
        lines.append("")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


async def _handle_vehicle_update(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Update a vehicle's details.

    Usage:
      /fahrzeug update <ID> type <Typ>
      /fahrzeug update <ID> plate <Kennzeichen>
      /fahrzeug update <ID> capacity <N>
      /fahrzeug update <ID> notes <Text>
    """
    args = context.args[1:]  # Skip "update"

    if len(args) < 2:
        await update.message.reply_text(
            "❌ *Unzureichende Argumente.*\n\n"
            "Verwendung:\n"
            "`/fahrzeug update <ID> type <Sitz|Liege|Rad|KTW>`\n"
            "`/fahrzeug update <ID> plate <Kennzeichen>`\n"
            "`/fahrzeug update <ID> capacity <N>`\n"
            "`/fahrzeug update <ID> notes <Text>`",
            parse_mode="Markdown",
        )
        return

    vehicle_id = _parse_int_arg(args[0])
    if vehicle_id is None:
        await update.message.reply_text(
            f"❌ Ungültige ID: `{args[0]}`. Bitte eine Zahl angeben.",
            parse_mode="Markdown",
        )
        return

    vehicle = await Vehicle.filter(id=vehicle_id).first()
    if vehicle is None:
        await update.message.reply_text(
            f"❌ Fahrzeug mit ID *{vehicle_id}* nicht gefunden.\n"
            f"Verwende `/fahrzeug list` um alle IDs zu sehen.",
            parse_mode="Markdown",
        )
        return

    field = args[1].lower()
    value_args = args[2:]

    if field == "type":
        if not value_args:
            await update.message.reply_text(
                "❌ Bitte einen Typ angeben: `Sitz`, `Liege`, `Rad`, `KTW`\n"
                "Beispiel: `/fahrzeug update 1 type KTW`",
                parse_mode="Markdown",
            )
            return
        new_type = value_args[0].upper()
        if new_type not in ("SITZ", "LIEGE", "RAD", "KTW"):
            await update.message.reply_text(
                f"❌ Ungültiger Typ: `{new_type}`. Erlaubt: Sitz, Liege, Rad, KTW",
                parse_mode="Markdown",
            )
            return
        old_type = vehicle.vehicle_type
        vehicle.vehicle_type = new_type
        await db_retry(lambda: vehicle.save(), operation_name="vehicle_save")
        await update.message.reply_text(
            f"✅ Typ von *{vehicle.license_plate}* aktualisiert:\n"
            f"`{old_type}` → `{new_type}`",
            parse_mode="Markdown",
        )

    elif field == "plate":
        if not value_args:
            await update.message.reply_text(
                "❌ Bitte das neue Kennzeichen angeben.\n"
                "Beispiel: `/fahrzeug update 1 plate B-NE-9999`",
                parse_mode="Markdown",
            )
            return
        new_plate = value_args[0].upper()
        # Check uniqueness
        dup = await Vehicle.filter(license_plate__iexact=new_plate).first()
        if dup and dup.id != vehicle.id:
            await update.message.reply_text(
                f"⚠️ Kennzeichen *{new_plate}* ist bereits vergeben (ID {dup.id}).",
                parse_mode="Markdown",
            )
            return
        old_plate = vehicle.license_plate
        vehicle.license_plate = new_plate
        await db_retry(lambda: vehicle.save(), operation_name="vehicle_save")
        await update.message.reply_text(
            f"✅ Kennzeichen aktualisiert:\n`{old_plate}` → `{new_plate}`",
            parse_mode="Markdown",
        )

    elif field == "capacity":
        if not value_args:
            await update.message.reply_text(
                "❌ Bitte die neue Kapazität angeben.\n"
                "Beispiel: `/fahrzeug update 1 capacity 2`",
                parse_mode="Markdown",
            )
            return
        new_cap = _parse_int_arg(value_args[0])
        if new_cap is None or new_cap < 1:
            await update.message.reply_text(
                f"❌ Ungültige Kapazität: `{value_args[0]}`. Bitte eine positive Zahl angeben.",
                parse_mode="Markdown",
            )
            return
        old_cap = vehicle.capacity
        vehicle.capacity = new_cap
        await db_retry(lambda: vehicle.save(), operation_name="vehicle_save")
        await update.message.reply_text(
            f"✅ Kapazität von *{vehicle.license_plate}* aktualisiert:\n"
            f"`{old_cap}` → `{new_cap}`",
            parse_mode="Markdown",
        )

    elif field == "notes":
        if not value_args:
            # Clear notes
            vehicle.notes = None
            await db_retry(lambda: vehicle.save(), operation_name="vehicle_save")
            await update.message.reply_text(
                f"✅ Notiz für *{vehicle.license_plate}* gelöscht.",
                parse_mode="Markdown",
            )
            return
        new_notes = " ".join(value_args)
        vehicle.notes = new_notes
        await db_retry(lambda: vehicle.save(), operation_name="vehicle_save")
        await update.message.reply_text(
            f"✅ Notiz für *{vehicle.license_plate}* aktualisiert:\n"
            f"`{new_notes}`",
            parse_mode="Markdown",
        )

    else:
        await update.message.reply_text(
            f"❓ Unbekanntes Feld: `{field}`\n\n"
            "Verfügbare Felder: `type`, `plate`, `capacity`, `notes`",
            parse_mode="Markdown",
        )


async def _handle_vehicle_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Delete a vehicle — requires explicit confirmation.

    Usage:
      /fahrzeug delete <ID>         → asks for confirmation
      /fahrzeug delete <ID> confirm → actually deletes
    """
    args = context.args[1:]  # Skip "delete"

    if len(args) < 1:
        await update.message.reply_text(
            "❌ Bitte die ID des Fahrzeugs angeben.\n"
            "Beispiel: `/fahrzeug delete 3`",
            parse_mode="Markdown",
        )
        return

    vehicle_id = _parse_int_arg(args[0])
    if vehicle_id is None:
        await update.message.reply_text(
            f"❌ Ungültige ID: `{args[0]}`",
            parse_mode="Markdown",
        )
        return

    vehicle = await Vehicle.filter(id=vehicle_id).first()
    if vehicle is None:
        await update.message.reply_text(
            f"❌ Fahrzeug mit ID *{vehicle_id}* nicht gefunden.",
            parse_mode="Markdown",
        )
        return

    # Check if confirmation is provided
    confirmed = len(args) >= 2 and args[1].lower() == "confirm"

    if not confirmed:
        await update.message.reply_text(
            f"⚠️ *Wirklich löschen?*\n\n"
            f"Fahrzeug: *{vehicle.notes or '—'}* ({vehicle.license_plate})\n"
            f"ID: {vehicle.id}\n"
            f"Typ: {vehicle.vehicle_type}\n\n"
            f"Zum Bestätigen: `/fahrzeug delete {vehicle.id} confirm`\n"
            f"⚠️ Das Fahrzeug wird endgültig gelöscht!",
            parse_mode="Markdown",
        )
        return

    plate = vehicle.license_plate
    vehicle_id_saved = vehicle.id

    await db_retry(lambda: vehicle.delete(), operation_name="vehicle_delete")

    logger.info("Vehicle deleted", vehicle_id=vehicle_id_saved, plate=plate)

    await update.message.reply_text(
        f"🗑️ Fahrzeug *{plate}* (ID {vehicle_id_saved}) wurde *gelöscht*.",
        parse_mode="Markdown",
    )


# =============================================================================
# /dashboard — Daily Trip Dashboard with Color-Coded Status + Manual Assignment
# =============================================================================

# Status color coding (emoji + label)
STATUS_EMOJI: dict[str, str] = {
    "geplant": "🔴",
    "zugewiesen": "🟡",
    "anfahrt": "🔵",
    "angekommen": "🔵",
    "patient_an_bord": "🔵",
    "unterwegs": "🔵",
    "abgesetzt": "🟠",
    "abgeschlossen": "🟢",
    "storniert": "⚫",
    "problem": "🔴",
}

STATUS_LABEL: dict[str, str] = {
    "geplant": "Geplant",
    "zugewiesen": "Zugewiesen",
    "anfahrt": "Anfahrt",
    "angekommen": "Angekommen",
    "patient_an_bord": "Patient an Bord",
    "unterwegs": "Unterwegs",
    "abgesetzt": "Abgesetzt",
    "abgeschlossen": "Abgeschlossen",
    "storniert": "Storniert",
    "problem": "Problem",
}

# Which statuses allow manual assignment
ASSIGNABLE_STATUSES = frozenset({"geplant"})


def _format_trip_line(trip) -> str:
    """Format a single trip as a compact, color-coded line.

    Returns a markdown-formatted line with status emoji, trip ID, patient name,
    route, scheduled time, and driver.
    """
    emoji = STATUS_EMOJI.get(trip.status, "❓")
    label = STATUS_LABEL.get(trip.status, trip.status)

    patient_name = trip.patient.name if trip.patient else "?"
    pickup = trip.pickup_addr or "?"
    dest = trip.dest_addr or "?"
    pickup_time = (
        trip.scheduled_pickup.strftime("%H:%M")
        if trip.scheduled_pickup
        else "??:??"
    )
    driver_name = trip.driver.name if trip.driver else "Kein Fahrer"

    return (
        f"{emoji} *\\#{trip.id}* | {pickup_time} | {patient_name}\\n"
        f"  {pickup} → {dest}\\n"
        f"  _{label}_ · 🧑 {driver_name}"
    )


def _build_dashboard_text(trips: list, display_date: date) -> str:
    """Build the full dashboard message text from a list of trips.

    Includes a header with date, summary counts by status, then each trip line.
    """
    date_str = display_date.strftime("%d.%m.%Y")
    header = f"🚑 *Tages-Dashboard — {date_str}*"

    if not trips:
        return f"{header}\\n\\n_✅ Keine Fahrten für heute._"

    # Summary counts
    counts: dict[str, int] = {}
    for t in trips:
        label = STATUS_LABEL.get(t.status, t.status)
        counts[label] = counts.get(label, 0) + 1

    summary = " · ".join(f"{label}: {n}" for label, n in sorted(counts.items()))

    # Trip lines
    lines = [header, f"_{summary}_", "", "━━━━━━━━━━━━━━━━━━"]
    for trip in sorted(trips, key=lambda t: t.scheduled_pickup or datetime.min):
        lines.append(_format_trip_line(trip))
        lines.append("")

    return "\\n".join(lines)


def _build_assignment_keyboard(trip, drivers: list):
    """Build an inline keyboard for assigning a driver to a trip.

    Returns a list of button rows (list of InlineKeyboardButton), or None if
    the trip is not assignable or no drivers are available.
    """
    from telegram import InlineKeyboardButton

    if trip.status not in ASSIGNABLE_STATUSES:
        return None
    if not drivers:
        return None

    # One row of driver buttons
    row = [
        InlineKeyboardButton(
            text=d.name,
            callback_data=f"assign_{trip.id}_{d.id}",
        )
        for d in drivers
    ]
    return [row]


# --- DB helpers (testable independently) ---


async def _fetch_todays_trips():
    """Fetch all trips scheduled for today, with patient and driver relations."""
    from datetime import datetime

    from krankenfahrt.models.schema import Trip

    now = datetime.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    return await (
        Trip.filter(scheduled_pickup__gte=day_start, scheduled_pickup__lte=day_end)
        .prefetch_related("patient", "driver")
        .all()
    )


async def _fetch_active_drivers():
    """Fetch all active drivers."""
    from krankenfahrt.models.schema import Driver

    return await Driver.filter(active=True).all()


async def _assign_driver(trip_id: int, driver_id: int):
    """Assign a driver to a trip and update the trip status.

    Raises ValueError if the trip or driver doesn't exist.
    """
    from krankenfahrt.models.schema import Driver, Trip

    trip = await Trip.filter(id=trip_id).first()
    if trip is None:
        raise ValueError(f"Trip {trip_id} nicht gefunden")

    driver = await Driver.filter(id=driver_id, active=True).first()
    if driver is None:
        raise ValueError(f"Fahrer {driver_id} nicht gefunden oder inaktiv")

    trip.driver = driver
    trip.status = "zugewiesen"
    await trip.save()


# --- Command handler ---


@_require_admin
async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /dashboard — show today's trips with color codes and assignment buttons."""
    today = date.today()

    await update.message.reply_text("⏳ Lade heutige Fahrten...")

    try:
        trips = await _fetch_todays_trips()
        drivers = await _fetch_active_drivers()
    except Exception as e:
        logger.exception("Dashboard query failed")
        await update.message.reply_text(
            f"❌ Fehler beim Laden der Fahrten: {e}"
        )
        return

    text = _build_dashboard_text(trips, today)

    # Build inline keyboard for assignable trips
    keyboard_rows = []
    for trip in trips:
        kb = _build_assignment_keyboard(trip, drivers)
        if kb:
            keyboard_rows.extend(kb)

    if keyboard_rows:
        from telegram import InlineKeyboardMarkup

        reply_markup = InlineKeyboardMarkup(keyboard_rows)
        await update.message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
    else:
        await update.message.reply_text(text, parse_mode="Markdown")


# --- Callback handler for assignment buttons ---


@_require_admin
async def cmd_assign_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle inline keyboard callback for driver assignment.

    Callback data format: assign_<trip_id>_<driver_id>
    """
    query = update.callback_query
    await query.answer()  # Acknowledge the button press

    data = query.data or ""
    if not data.startswith("assign_"):
        return

    parts = data.split("_")
    if len(parts) != 3:
        await query.edit_message_text("❌ Ungültige Zuweisungsdaten.")
        return

    try:
        trip_id = int(parts[1])
        driver_id = int(parts[2])
    except ValueError:
        await query.edit_message_text("❌ Ungültige Zuweisungsdaten.")
        return

    try:
        await _assign_driver(trip_id, driver_id)
    except ValueError as e:
        await query.edit_message_text(f"❌ {e}")
        return
    except Exception as e:
        logger.exception("Assignment failed")
        await query.edit_message_text(f"❌ Fehler bei der Zuweisung: {e}")
        return

    # Refresh the dashboard after assignment
    today = date.today()
    trips = await _fetch_todays_trips()
    drivers = await _fetch_active_drivers()
    text = _build_dashboard_text(trips, today)

    keyboard_rows = []
    for trip in trips:
        kb = _build_assignment_keyboard(trip, drivers)
        if kb:
            keyboard_rows.extend(kb)

    if keyboard_rows:
        from telegram import InlineKeyboardMarkup

        reply_markup = InlineKeyboardMarkup(keyboard_rows)
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=reply_markup,
        )
    else:
        await query.edit_message_text(text, parse_mode="Markdown")


# =============================================================================
# Natural Language Handler (Chef)
# =============================================================================


async def handle_natural_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle natural language messages: classify intent via NLU, route to handler."""
    text = update.message.text.strip()
    if not text:
        return

    from krankenfahrt.services.nlu import classify_chef

    intent = await classify_chef(text)
    logger.info("Chef NLU: %s → intent=%s (%.2f)", text[:60], intent.intent, intent.confidence)

    if intent.intent == "dashboard":
        await cmd_dashboard(update, context)
    elif intent.intent == "driver_list":
        await _handle_driver_list(update, context)
    elif intent.intent == "export":
        await cmd_export(update, context)
    elif intent.intent == "escalate":
        await _handle_escalation_list(update, context)
    elif intent.intent == "driver_add":
        # Extract name/phone from text using LLM or fall back to /fahrer add hint
        await update.message.reply_text(
            "📋 *Fahrer anlegen* — nutze dafür bitte:\n"
            "`/fahrer add <Vorname> <Nachname> <Telefon> [Telegram-ID]`\n\n"
            "Beispiel: `/fahrer add Max Mustermann 017612345678`",
            parse_mode="Markdown",
        )
    elif intent.intent == "assign_trip":
        # Guide user to dashboard for assignment
        await update.message.reply_text(
            "🔀 *Fahrt zuweisen* — schau dir das Dashboard an:\n"
            "`/dashboard` zeigt alle Fahrten mit Zuweisen-Buttons.",
            parse_mode="Markdown",
        )
    elif intent.intent == "info":
        # Show dashboard — most useful default for "what's going on"
        await cmd_dashboard(update, context)
    else:
        await update.message.reply_text(
            "❓ Das habe ich nicht verstanden. Sag einfach was du tun möchtest — "
            "z.B. \"Dashboard\", \"Fahrerliste\", \"Export\" — oder nutze /start für Hilfe."
        )


# =============================================================================
# Handler Registration
# =============================================================================


def register_handlers(app: Application) -> None:
    """Register all Chef-Bot command handlers."""
    from telegram.ext import CallbackQueryHandler, MessageHandler, filters

    # Natural language first (catches non-command text)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_natural_message))

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("fahrer", cmd_fahrer))
    app.add_handler(CommandHandler("fahrzeug", cmd_fahrzeug))
    app.add_handler(CallbackQueryHandler(cmd_assign_callback, pattern="^assign_"))

    logger.info(
        "Chef-Bot handlers registered: NLU + start, dashboard, export, fahrer, fahrzeug"
    )
