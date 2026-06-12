"""Natural language response generation.

Fetches relevant data from the database and uses DeepSeek to formulate
a conversational, context-aware response — not just structured dumps.
"""
from __future__ import annotations

import structlog

from krankenfahrt.config import config

logger = structlog.get_logger(__name__)


async def _llm_generate(system_prompt: str, user_message: str, max_tokens: int = 300) -> str:
    """Call DeepSeek to generate a natural language response."""
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{config.DEEPSEEK_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0.3,
                    "max_tokens": max_tokens,
                },
                timeout=15.0,
            )
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception:
        logger.warning("LLM response generation failed", exc_info=True)
        return None


async def generate_driver_response(text: str, telegram_id: int) -> str:
    """Generate a natural response for a driver's message.

    Fetches the driver's upcoming trips and asks DeepSeek to formulate
    a conversational German response.
    """
    from datetime import datetime as dt

    from krankenfahrt.models.schema import Driver, Trip

    try:
        driver = await Driver.get(telegram_id=telegram_id)
    except Exception:
        return (
            "Du bist nicht als Fahrer registriert. "
            "Bitte wende dich an deinen Disponenten."
        )

    # Fetch upcoming trips
    now = dt.now()
    tomorrow = now.replace(hour=0, minute=0, second=0)  # today start
    trips = await Trip.filter(
        driver_id=driver.id,
        scheduled_pickup__gte=tomorrow,
    ).prefetch_related("patient").order_by("scheduled_pickup").limit(10)

    # Build trip data for the LLM
    if trips:
        trip_lines = []
        for t in trips:
            patient_name = t.patient.name if t.patient else "?"
            trip_lines.append(
                f"- {t.scheduled_pickup.strftime('%d.%m.%Y %H:%M')}: "
                f"{t.pickup_addr} → {t.dest_addr} ({patient_name}, Status: {t.status})"
            )
        trip_data = "\n".join(trip_lines)
    else:
        trip_data = "Keine anstehenden Fahrten."

    system = (
        "Du bist ein freundlicher Fahrer-Assistent. Der Nutzer IST der Fahrer "
        "(nicht der Patient). Sprich ihn mit seinem Vornamen an, dutze ihn. "
        "Antworte auf Deutsch, kurz und natürlich (1-3 Sätze). "
        "Nutze die Fahrten-Daten: Nenne Patientennamen, Uhrzeiten und Ziele. "
        "Keine Aufzählungen — formuliere fließenden Text. "
        "Wenn der Fahrer fragt ob er jemanden 'fahren' kann: Er meint ob er "
        "ALS FAHRER eingeteilt ist — nicht ob er selbst gefahren werden will."
    )

    user = (
        f"Fahrer '{driver.name}' fragt: \"{text}\"\n\n"
        f"Seine anstehenden Fahrten:\n{trip_data}\n\n"
        f"Antworte natürlich und hilfreich auf Deutsch."
    )

    response = await _llm_generate(system, user)
    if response:
        return response

    # Fallback: simple structured output
    if trips:
        lines = [f"🚗 *Deine Fahrten, {driver.name}:*"]
        for t in trips[:5]:
            pname = t.patient.name if t.patient else "?"
            lines.append(
                f"• {t.scheduled_pickup.strftime('%d.%m %H:%M')} — "
                f"{pname}: {t.pickup_addr} → {t.dest_addr}"
            )
        return "\n".join(lines)
    return "Du hast aktuell keine anstehenden Fahrten."


async def generate_chef_response(text: str) -> str:
    """Generate a natural response for the chef/dispatcher's message."""
    from datetime import datetime as dt

    from krankenfahrt.models.schema import Driver, Trip

    # Fetch today's trips
    now = dt.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    trips = await Trip.filter(
        scheduled_pickup__gte=day_start,
        scheduled_pickup__lte=day_end,
    ).prefetch_related("patient", "driver").order_by("scheduled_pickup").all()

    drivers = await Driver.filter(active=True).all()

    if trips:
        trip_lines = []
        for t in trips[:15]:
            patient_name = t.patient.name if t.patient else "?"
            driver_name = t.driver.name if t.driver else "❌ nicht zugewiesen"
            trip_lines.append(
                f"- {t.scheduled_pickup.strftime('%H:%M')}: "
                f"{patient_name} ({t.pickup_addr} → {t.dest_addr}), "
                f"Fahrer: {driver_name}, Status: {t.status}"
            )
        trip_data = "\n".join(trip_lines)
    else:
        trip_data = "Keine Fahrten für heute."

    driver_data = ", ".join([d.name for d in drivers]) if drivers else "Keine Fahrer registriert"

    system = (
        "Du bist ein Disponenten-Assistent für einen Krankentransport-Betrieb. "
        "Antworte auf Deutsch, professionell und direkt (2-3 Sätze). "
        "Gib einen schnellen Überblick: Anzahl Fahrten, zugewiesen/unzugewiesen, "
        "aktive Fahrer. Nenne konkrete Uhrzeiten und Namen. "
        "Keine Aufzählungen — formuliere Fließtext."
    )

    user = (
        f"Der Disponent fragt: \"{text}\"\n\n"
        f"Heutige Fahrten ({len(trips)}):\n{trip_data}\n\n"
        f"Aktive Fahrer ({len(drivers)}): {driver_data}\n\n"
        f"Antworte direkt und professionell."
    )

    response = await _llm_generate(system, user)
    if response:
        return response

    # Fallback: structured dashboard
    assigned = sum(1 for t in trips if t.driver_id)
    unassigned = len(trips) - assigned
    return (
        f"📊 *Heute:* {len(trips)} Fahrten\\n"
        f"✅ {assigned} zugewiesen | ⚠️ {unassigned} offen\\n"
        f"👤 {len(drivers)} Fahrer aktiv\\n\\n"
        f"/dashboard für Details"
    )
