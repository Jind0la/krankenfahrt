"""Notification service — sends messages to patients, drivers, chef."""

from datetime import datetime
from typing import Optional


# German message templates
class Messages:
    """All user-facing messages in German."""

    # --- Patient Messages ---
    PATIENT_TRIP_BOOKED = (
        "✅ **Fahrt gebucht!**\n\n"
        "📅 {date} um {time}\n"
        "📍 Von: {pickup}\n"
        "🏥 Nach: {dest}\n"
        "🚗 Fahrzeugtyp: {vehicle}\n\n"
        "Wir melden uns, sobald ein Fahrer zugeteilt ist."
    )

    PATIENT_DRIVER_ASSIGNED = (
        "👋 **{driver_name} ist Ihr Fahrer!**\n\n"
        "🚗 {vehicle_desc}\n"
        "📞 Bei Fragen: {driver_phone}\n\n"
        "Am Abholtag schicken wir Ihnen eine Benachrichtigung mit Live-Standort."
    )

    PATIENT_DRIVER_EN_ROUTE = (
        "🚗 **{driver_name} ist unterwegs!**\n"
        "📍 Noch ca. {eta_min} Minuten bis zur Abholung.\n"
        "📡 Live-Standort wird geteilt..."
    )

    PATIENT_DRIVER_ARRIVED = (
        "📍 **{driver_name} ist angekommen!**\n"
        "🚗 Fahrzeug: {vehicle_desc}\n"
        "Bitte kommen Sie zur Abholung."
    )

    PATIENT_DROPPED_OFF = (
        "✅ **Sie wurden abgesetzt um {time}.**\n\n"
        "Gute Besserung! Bei Rückfragen: {company_name}"
    )

    PATIENT_REMINDER = (
        "⏰ **Erinnerung: Morgen ist Ihre Fahrt!**\n\n"
        "📅 {date} um {time}\n"
        "📍 Abholung: {pickup}\n"
        "🏥 Ziel: {dest}\n\n"
        "Ihr Fahrer wird sich melden."
    )

    PATIENT_CANCELLED = (
        "❌ Fahrt am {date} um {time} wurde storniert."
    )

    # --- Driver Messages ---
    DRIVER_NEW_TRIP = (
        "📋 **Neue Fahrt!**\n\n"
        "👤 {patient_name}\n"
        "⏰ Abholung: {pickup_time}\n"
        "📍 Von: {pickup_addr}\n"
        "🏥 Nach: {dest_addr}\n"
        "🚗 Typ: {vehicle_type}\n"
        "{special_needs}\n\n"
        "[🗺 Navigation]({nav_link})"
    )

    DRIVER_TRIP_ACTION_PROMPT = (
        "Bitte Aktion wählen:"
    )

    DRIVER_DAY_SUMMARY = (
        "📅 **Heutige Fahrten ({count})**\n\n{trips_list}"
    )

    # --- Chef Messages ---
    CHEF_ESCALATION = (
        "⚠️ **Eskalation!**\n\n"
        "Fahrt #{trip_id}: {patient_name}\n"
        "Fahrer: {driver_name}\n"
        "Problem: {problem}\n\n"
        "[Optionen anzeigen]"
    )

    CHEF_DAILY_DASHBOARD = (
        "📊 **Tagesübersicht {date}**\n\n"
        "✅ Abgeschlossen: {done}\n"
        "🔄 Aktiv: {active}\n"
        "⏳ Geplant: {planned}\n"
        "❌ Storniert: {cancelled}\n"
        "⚠️ Probleme: {problems}"
    )

    @staticmethod
    def format_time(dt: datetime) -> str:
        return dt.strftime("%H:%M")

    @staticmethod
    def format_date(dt: datetime) -> str:
        # German date format
        months = [
            "Januar", "Februar", "März", "April", "Mai", "Juni",
            "Juli", "August", "September", "Oktober", "November", "Dezember"
        ]
        return f"{dt.day}. {months[dt.month - 1]} {dt.year}"
