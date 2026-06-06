"""Chef-Bot (@FahrtenChef): Dispatcher/Owner interface.

Commands:
  /dashboard  — Tagesübersicht aller Fahrten
  /export     — CSV-Export der Abrechnungsdaten für einen Zeitraum
  /fahrer     — Fahrerverwaltung (anlegen, deaktivieren)
  /fahrzeug   — Fahrzeugverwaltung
"""

from datetime import date, datetime, timedelta

import structlog
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from krankenfahrt.config import config
from krankenfahrt.services.billing import ExportFilters, export_billing_csv

logger = structlog.get_logger(__name__)

# --- Hilfsfunktionen ---


def _parse_date_arg(text: str) -> date | None:
    """Parse ein Datum im Format DD.MM.YYYY oder YYYY-MM-DD."""
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


# --- Command Handler ---


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start-Nachricht mit verfügbaren Befehlen."""
    await update.message.reply_text(
        "🚑 *FahrtenChef* — Dein Disponenten-Cockpit\n\n"
        "Verfügbare Befehle:\n"
        "/dashboard — Heutige Fahrten im Überblick\n"
        "/export \\[von] \\[bis] — Abrechnungs-CSV exportieren\n"
        "  z.B. `/export 01.06.2026 30.06.2026`\n"
        "/fahrer — Fahrerverwaltung\n"
        "/fahrzeug — Fahrzeugverwaltung",
        parse_mode="Markdown",
    )


async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """CSV-Export der Abrechnungsdaten.

    Usage: /export [von] [bis]
    Ohne Argumente: alle Fahrten exportieren.
    Mit einem Datum: ab diesem Datum.
    Mit zwei Daten: Zeitraum von–bis.
    """
    args = context.args  # Liste der Wörter nach /export
    filters = ExportFilters()

    if len(args) >= 1:
        date_from = _parse_date_arg(args[0])
        if date_from is None:
            await update.message.reply_text(
                "❌ Ungültiges Datum. Bitte im Format DD.MM.YYYY angeben, z.B. `/export 01.06.2026`",
                parse_mode="Markdown",
            )
            return
        filters.date_from = date_from

    if len(args) >= 2:
        date_to = _parse_date_arg(args[1])
        if date_to is None:
            await update.message.reply_text(
                "❌ Ungültiges Enddatum. Bitte im Format DD.MM.YYYY angeben.",
                parse_mode="Markdown",
            )
            return
        filters.date_to = date_to

    await update.message.reply_text(
        "⏳ Exportiere Abrechnungsdaten..."
        + (
            f"\nZeitraum: {filters.date_from.strftime('%d.%m.%Y')} – {filters.date_to.strftime('%d.%m.%Y')}"
            if filters.date_from
            else ""
        ),
    )

    try:
        filepath = await export_billing_csv(filters=filters)
        with open(filepath, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=filepath.name,
                caption=(
                    f"📊 Abrechnungs-Export\n"
                    f"{'Zeitraum: ' + filters.date_from.strftime('%d.%m.%Y') + ' – ' + filters.date_to.strftime('%d.%m.%Y') if filters.date_from else 'Alle Fahrten'}\n"
                    f"Datei: `{filepath.name}`"
                ),
                parse_mode="Markdown",
            )
    except Exception as e:
        logger.exception("Export failed")
        await update.message.reply_text(
            f"❌ Export fehlgeschlagen: {e}",
        )


# --- Handler-Registrierung ---


def register_handlers(app: Application) -> None:
    """Registriere alle Chef-Bot Command-Handler."""
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("export", cmd_export))
    logger.info("Chef-Bot handlers registered: start, export")
