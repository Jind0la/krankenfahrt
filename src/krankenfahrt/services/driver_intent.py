"""Driver Intent Extraction Service.

Analyzes transcribed voice messages from drivers to extract status-update
intents that map to Trip state machine triggers.

Uses DeepSeek LLM when available, with a rule-based fallback for offline/rapid
classification.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import structlog

from krankenfahrt.config import config

logger = structlog.get_logger(__name__)

DRIVER_INTENT_SYSTEM_PROMPT = """Du bist ein Intent-Classifier für Krankentransport-Fahrer.
Extrahiere aus Sprachnachrichten-Transkripten die Fahraktion des Fahrers.
Antworte AUSSCHLIESSLICH mit JSON.

MÖGLICHE AKTIONEN:
- "losfahren": Fahrer startet Fahrt zum Patienten
- "ankunft_melden": Fahrer ist am Abholort angekommen
- "patient_aufnehmen": Patient ist eingestiegen
- "fahrt_beginnen": Fahrt zum Ziel beginnt
- "patient_absetzen": Patient wurde abgesetzt
- "abschliessen": Fahrt fertig, abschließen
- "problem_melden": Es gibt ein Problem
- "stornieren": Fahrt muss storniert werden
- "pause": Fahrer macht Pause/unabhängig von Fahrt
- "unknown": Keine klare Fahraktion erkennbar

FELDER:
- action: string (eine der obigen Aktionen)
- trigger: string (der State-Machine-Trigger, gleich wie action außer bei 'pause' → null)
- confidence: 0.0-1.0
- params: object mit Zusatzinfos (trip_reference, note, etc.)
"""

DRIVER_INTENT_EXAMPLES = """Beispiele:

"ok ich fahre jetzt los zur ersten Fahrt"
→ {"action":"losfahren","trigger":"losfahren","confidence":0.95,"params":{"note":"Zur ersten Fahrt"}}

"bin angekommen beim Patienten"
→ {"action":"ankunft_melden","trigger":"ankunft_melden","confidence":0.95,"params":{}}

"Patient ist eingestiegen, wir können los"
→ {"action":"patient_aufnehmen","trigger":"patient_aufnehmen","confidence":0.95,"params":{}}

"wir fahren jetzt zum Klinikum"
→ {"action":"fahrt_beginnen","trigger":"fahrt_beginnen","confidence":0.90,"params":{}}

"Patient ist abgesetzt am Klinikum Nord"
→ {"action":"patient_absetzen","trigger":"patient_absetzen","confidence":0.95,"params":{}}

"Fahrt fertig, abschließen"
→ {"action":"abschliessen","trigger":"abschliessen","confidence":0.95,"params":{}}

"Patient nicht zuhause, keiner macht auf"
→ {"action":"problem_melden","trigger":"problem_melden","confidence":0.90,"params":{"note":"Patient nicht zuhause"}}

"die Fahrt muss storniert werden der Patient hat abgesagt"
→ {"action":"stornieren","trigger":"stornieren","confidence":0.95,"params":{}}

"ich mach jetzt Pause"
→ {"action":"pause","trigger":null,"confidence":0.95,"params":{}}

"das Wetter ist schön heute"
→ {"action":"unknown","trigger":null,"confidence":0.90,"params":{}}
"""

# --- Keyword patterns for rule-based fallback ---
_RULE_PATTERNS: list[tuple[str, Optional[str], list[str]]] = [
    # (action, trigger, [keyword patterns])
    ("stornieren", "stornieren", [
        r"\bstornier", r"\babsagen\b", r"\babsage\b", r"\bstorno\b",
    ]),
    ("abschliessen", "abschliessen", [
        r"\babschlie[ßs]en\b", r"\bfertig\b", r"\berledigt\b",
        r"\bfeierabend\b", r"\bfahrt.*(?:vorbei|ende|fertig)",
    ]),
    ("patient_absetzen", "patient_absetzen", [
        r"\babgesetzt\b", r"\babsetzen\b", r"\bausgestiegen\b",
        r"\bpatient.*(?:raus|weg|abgeliefert)",
    ]),
    ("fahrt_beginnen", "fahrt_beginnen", [
        r"\bfahrt.*(?:beginnt|start|los)", r"\bunterwegs\b",
        r"\bauf.*weg\b", r"\bweiterfahrt\b", r"\bfahren.*los\b",
    ]),
    ("patient_aufnehmen", "patient_aufnehmen", [
        r"\bpatient.*(?:an bord|eingestiegen|aufgenommen|drin)",
        r"\beingestiegen\b", r"\ban bord\b", r"\baufgenommen\b",
    ]),
    ("ankunft_melden", "ankunft_melden", [
        r"\bangekommen\b", r"\bankunft\b", r"\bda\b.*\b(?:patient|abhol)",
        r"\bvor.*ort\b", r"\bwarte\b.*\bpatient\b",
    ]),
    ("losfahren", "losfahren", [
        r"\blosfahren\b", r"\blos\b.*\bfahrt\b", r"\banfahrt\b",
        r"\bstarte\b.*\bfahrt\b", r"\bmach.*\bauf.*weg\b",
        r"\bfahre.*\blos\b", r"\bauf.*\bfahrt\b",
    ]),
    ("problem_melden", "problem_melden", [
        r"\bproblem\b", r"\bgeht nicht\b", r"\bkein.*\b(?:patient|da)",
        r"\bverspätung\b", r"\bunfall\b", r"\bstau\b",
        r"\bpatient.*\b(?:nicht|fehlt|weg|krank)",
        r"\bnicht.*\b(?:da|zuhause|erreichbar)",
    ]),
    ("pause", None, [
        r"\bpause\b", r"\bkaffee\b", r"\bessen\b", r"\btoilette\b",
        r"\bdurchatmen\b", r"\bkurz.*\b(?:weg|raus)",
    ]),
]


@dataclass
class DriverIntent:
    """Structured intent extracted from a driver's voice transcript.

    Attributes:
        action: The classified action (e.g., 'losfahren', 'pause', 'unknown').
        trigger: The state-machine trigger name, or None for non-trip actions.
        trip_reference: Human-readable trip reference if mentioned.
        confidence: 0.0-1.0 confidence score.
        params: Additional extracted parameters (note, trip_id hints, etc.).
    """

    action: str = "unknown"
    trigger: Optional[str] = None
    trip_reference: Optional[str] = None
    confidence: float = 0.0
    params: dict = field(default_factory=dict)


def _rule_based_driver_intent(transcript: str) -> DriverIntent:
    """Keyword-based fallback classifier for driver transcripts.

    Walk the pattern list in priority order (stornieren first — it's most
    critical to catch) and return the first match. Falls through to 'unknown'
    when nothing matches.
    """
    text = transcript.lower().strip()

    for action, trigger, patterns in _RULE_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text):
                confidence = 0.80  # rule-based is less confident than LLM
                note_match = re.search(r"(?:note|info|grund|bemerkung):?\s*(.+)", text)
                params = {}
                if note_match:
                    params["note"] = note_match.group(1).strip()
                return DriverIntent(
                    action=action,
                    trigger=trigger,
                    confidence=confidence,
                    params=params,
                )

    return DriverIntent(action="unknown", trigger=None, confidence=0.70, params={})


async def extract_driver_intent(transcript: str, use_llm: bool = True) -> DriverIntent:
    """Extract a DriverIntent from a transcribed voice message.

    Uses the DeepSeek LLM by default; falls back to rule-based classification
    when the LLM is unavailable, times out, or use_llm=False.

    Args:
        transcript: The transcribed text from the voice message.
        use_llm: If False, skip LLM and use rule-based classification directly.

    Returns:
        DriverIntent with the classified action, trigger, and confidence.
    """
    if not transcript or not transcript.strip():
        return DriverIntent(action="unknown", trigger=None, confidence=0.0)

    if not use_llm:
        return _rule_based_driver_intent(transcript)

    try:
        import httpx

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
                        {"role": "system", "content": DRIVER_INTENT_SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": f"Transkript: {transcript}\n\n{DRIVER_INTENT_EXAMPLES}",
                        },
                    ],
                    "temperature": 0.0,
                    "max_tokens": 200,
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
            return DriverIntent(
                action=parsed.get("action", "unknown"),
                trigger=parsed.get("trigger"),
                trip_reference=parsed.get("trip_reference"),
                confidence=parsed.get("confidence", 0.0),
                params=parsed.get("params", {}),
            )
    except Exception:
        logger.warning("LLM intent extraction failed, falling back to rule-based")
        return _rule_based_driver_intent(transcript)
