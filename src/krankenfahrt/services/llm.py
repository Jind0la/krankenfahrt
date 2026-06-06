"""LLM service — DeepSeek NLP for patient booking extraction."""

import json
from dataclasses import dataclass
from typing import Optional

import httpx

from krankenfahrt.config import config

NLU_SYSTEM_PROMPT = """Du bist ein Agent für Krankentransport-Buchungen. 
Extrahiere aus Patientennachrichten strukturierte Buchungsdaten.
Antworte AUSSCHLIESSLICH mit JSON.

ERKENNTE AKTIONEN:
- "book": Einmalige Fahrt buchen
- "recurring": Wiederkehrende Fahrt anlegen
- "cancel": Fahrt stornieren
- "change": Bestehende Fahrt ändern
- "info": Frage zu Fahrten/Status
- "other": Keine Buchungsabsicht

FELDER (nur wenn relevant):
- action: string (book/recurring/cancel/change/info/other)
- pickup_date: YYYY-MM-DD (wenn "morgen", nimm morgen. Wenn "übermorgen", den Tag danach)
- pickup_time: HH:MM (wenn "früh", nimm 07:30. "vormittags" = 09:00. "mittags" = 12:00)
- return_time: HH:MM oder null
- dest: Zieladresse oder Klinikname
- days: ["Mo","Mi","Fr"] für wiederkehrende Fahrten
- duration_min: Dauer in Minuten (für Termine mit fester Dauer)
- reason: Grund der Fahrt (Dialyse, Physio, Arztbesuch, etc.)
- confidence: 0.0-1.0 wie sicher du bist

BEISPIELE:
"Morgen 8 Uhr zur Dialyse Klinikum Nord, Rückfahrt ca. 12:30"
→ {"action":"book","pickup_date":"2026-06-07","pickup_time":"08:00","dest":"Klinikum Nord","return_time":"12:30","reason":"Dialyse","confidence":0.95}

"Jeden Montag und Mittwoch 9:00 zur Physio, bin ca 45 Minuten da"
→ {"action":"recurring","pickup_time":"09:00","dest":"Physio","days":["Mo","Mi"],"duration_min":45,"confidence":0.90}

"Kann ich meine Fahrt für morgen verschieben?"
→ {"action":"info","confidence":0.80}

"Heute war der Fahrer 20 Minuten zu spät"
→ {"action":"other","confidence":0.95}"""

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
    """Extract structured booking data from a natural language message."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{config.DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": NLU_SYSTEM_PROMPT},
                    {"role": "user", "content": message},
                ],
                "temperature": 0.0,
                "max_tokens": 300,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()
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
