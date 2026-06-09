"""LLM service — NLU for patient booking extraction with fallback chain.

Uses the resilience layer (call_with_fallback) which tries the primary
LLM provider, retries on transient errors, and falls back to a secondary
provider if configured.
"""

import json
from dataclasses import dataclass
from typing import Optional

from krankenfahrt.resilience.llm_fallback import call_with_fallback
from krankenfahrt.resilience.rate_limiter import get_global_limiter

NLU_SYSTEM_PROMPT = """Du bist ein Agent für Krankentransport-Buchungen. 
Extrahiere aus Patientennachrichten strukturierte Buchungsdaten.
Antworte AUSSCHLIESSLICH mit JSON.

HEUTE IST: {today_date}

ERKENNTE AKTIONEN:
- "book": Einmalige Fahrt buchen
- "recurring": Wiederkehrende Fahrt anlegen
- "cancel": Fahrt stornieren
- "change": Bestehende Fahrt ändern
- "info": Frage zu Fahrten/Status
- "other": Keine Buchungsabsicht

FELDER (nur wenn relevant):
- action: string (book/recurring/cancel/change/info/other)
- pickup_date: YYYY-MM-DD (berechne aus "morgen", "übermorgen", "nächsten Montag" etc. relativ zu HEUTE)
- pickup_time: HH:MM (wenn "früh", nimm 07:30. "vormittags" = 09:00. "mittags" = 12:00)
- return_time: HH:MM oder null
- dest: Zieladresse oder Klinikname
- days: ["Mo","Mi","Fr"] für wiederkehrende Fahrten
- duration_min: Dauer in Minuten (für Termine mit fester Dauer)
- reason: Grund der Fahrt (Dialyse, Physio, Arztbesuch, etc.)
- confidence: 0.0-1.0 wie sicher du bist

BEISPIELE:
"Morgen 8 Uhr zur Dialyse Klinikum Nord, Rückfahrt ca. 12:30"
→ {{"action":"book","pickup_date":"MORGEN","pickup_time":"08:00","dest":"Klinikum Nord","return_time":"12:30","reason":"Dialyse","confidence":0.95}}

"Jeden Montag und Mittwoch 9:00 zur Physio, bin ca 45 Minuten da"
→ {{"action":"recurring","pickup_time":"09:00","dest":"Physio","days":["Mo","Mi"],"duration_min":45,"confidence":0.90}}

"Kann ich meine Fahrt für morgen verschieben?"
→ {{"action":"info","confidence":0.80}}

"Heute war der Fahrer 20 Minuten zu spät"
→ {{"action":"other","confidence":0.95}}"""

@dataclass
class BookingIntent:
    action: str
    pickup_date: Optional[str] = None
    pickup_time: Optional[str] = None
    return_time: Optional[str] = None
    dest: Optional[str] = None
    days: Optional[list[str]] = None
    duration_min: Optional[int] = None
    reason: Optional[str] = None
    confidence: float = 0.0


async def extract_booking_intent(message: str) -> BookingIntent:
    """Extract structured booking data from a natural language message.

    Uses the LLM fallback chain: tries primary provider, retries on
    transient errors, falls back to secondary provider if configured,
    and rate-limits outbound API calls via token bucket.
    """
    from datetime import date as _date
    today = _date.today()
    today_str = today.strftime("%Y-%m-%d")
    prompt = NLU_SYSTEM_PROMPT.format(today_date=f"{today_str} ({today.strftime('%A')})")

    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": message},
    ]

    limiter = get_global_limiter()

    data = await call_with_fallback(
        messages,
        model=None,  # use provider defaults
        temperature=0.0,
        max_tokens=300,
        rate_limiter=limiter,
    )

    content = data["choices"][0]["message"]["content"]

    # Parse JSON from response (handle markdown code blocks)
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()

    parsed = json.loads(content)
    return BookingIntent(
        action=parsed.get("action", "other"),
        pickup_date=parsed.get("pickup_date"),
        pickup_time=parsed.get("pickup_time"),
        return_time=parsed.get("return_time"),
        dest=parsed.get("dest"),
        days=parsed.get("days"),
        duration_min=parsed.get("duration_min"),
        reason=parsed.get("reason"),
        confidence=parsed.get("confidence", 0.0),
    )
