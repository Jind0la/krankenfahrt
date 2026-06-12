"""NLU (Natural Language Understanding) for all three bots.

Replaces /command-driven interaction with natural language.
Uses DeepSeek Flash for intent classification with keyword fallback.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import structlog

from krankenfahrt.config import config

logger = structlog.get_logger(__name__)


# ── Chef-Bot Intents ──────────────────────────────────────────────────────

CHEF_NLU_PROMPT = """Du bist die NLU für einen Krankentransport-Disponenten-Bot.
Klassifiziere die Absicht der Nachricht. Antworte AUSSCHLIESSLICH mit JSON.

INTENTS:
- dashboard: Fahrten anzeigen, Tagesübersicht, "was steht heute an", "zeig mir die Fahrten"
- driver_add: Fahrer anlegen, "neuer Fahrer", "leg Max an", "fahrer registrieren"
- driver_list: Fahrer auflisten, "welche Fahrer", "wer ist aktiv", "liste fahrer"
- export: Daten exportieren, "csv", "pdf", "abrechnung", "exportieren"
- assign_trip: Fahrt zuweisen, "fahrer zuweisen", "Fahrt #X an Y"
- escalate: Eskalationen anzeigen, "probleme", "eskalationen", "was ist offen"
- info: Allgemeine Frage zum System, Hilfe
- unknown: Keine der obigen Absichten

BEISPIELE:
"Zeig mir die Fahrten für heute" → {"intent":"dashboard","confidence":0.95}
"Was steht an?" → {"intent":"dashboard","confidence":0.95}
"Leg mal den Max Mustermann als Fahrer an, Telefon 0176123456" → {"intent":"driver_add","confidence":0.90}
"Neuen Fahrer anlegen: Lisa Klein" → {"intent":"driver_add","confidence":0.90}
"Welche Fahrer haben wir?" → {"intent":"driver_list","confidence":0.95}
"Wer ist alles aktiv?" → {"intent":"driver_list","confidence":0.90}
"Exportier mir die Abrechnung" → {"intent":"export","confidence":0.95}
"Mach ne PDF" → {"intent":"export","confidence":0.85}
"Weis Fahrt 42 dem Ahmed zu" → {"intent":"assign_trip","confidence":0.90}
"Gibt's Probleme?" → {"intent":"escalate","confidence":0.85}"""


DRIVER_NLU_PROMPT = """Du bist die NLU für einen Krankentransport-Fahrer-Bot.
Klassifiziere die Absicht der Nachricht. Antworte AUSSCHLIESSLICH mit JSON.

INTENTS:
- heute: Tagesübersicht, "was hab ich heute", "meine fahrten", "tagesplan"
- pause: Pause machen, "pause", "kaffee", "essen", "kurz weg"
- ready: Wieder bereit nach Pause, "bin zurück", "weiter", "bereit"
- status: Status-Update für aktive Fahrt (losfahren, angekommen, patient an bord, abgesetzt, abschließen)
- problem: Problem melden, "patient nicht da", "unfall", "verspätung"
- info: Allgemeine Frage
- unknown: Keine der obigen

BEISPIELE:
"Was hab ich heute?" → {"intent":"heute","confidence":0.95}
"Ich mach jetzt Pause" → {"intent":"pause","confidence":0.95}
"Bin zurück" → {"intent":"ready","confidence":0.90}
"Ich fahr jetzt los" → {"intent":"status","confidence":0.90}
"Patient nicht zuhause" → {"intent":"problem","confidence":0.90}"""


PATIENT_NLU_PROMPT = """Du bist die NLU für einen Patientenfahrt-Bot.
Klassifiziere die Absicht der Nachricht. Antworte AUSSCHLIESSLICH mit JSON.

INTENTS:
- book: Fahrt buchen, "morgen zu Dialyse", "brauche Fahrt"
- info: Fahrten anzeigen, "wann kommt Fahrer", "meine fahrten", "status"
- cancel: Fahrt stornieren, "stornieren", "absagen", "brauche nicht"
- profile: Profil anzeigen/bearbeiten
- recurring: Wiederkehrende Fahrt einrichten
- unknown: Keine der obigen

BEISPIELE:
"Wann kommt mein Fahrer?" → {"intent":"info","confidence":0.95}
"Stornier meine Fahrt morgen" → {"intent":"cancel","confidence":0.90}
"Morgen 8 Uhr Klinikum Nord" → {"intent":"book","confidence":0.95}"""


@dataclass
class NluIntent:
    intent: str = "unknown"
    confidence: float = 0.0
    params: dict = field(default_factory=dict)
    raw_text: str = ""


# ── Keyword fallback patterns ──────────────────────────────────────────────

_CHEF_KEYWORDS = [
    ("dashboard", [r"(zeig|was)\s*(mir\s*)?(heute|fahrten|steht|an|dashboard|übersicht)"]),
    ("driver_add", [r"(leg|neuen?|erstell|fahrer\s*anlegen|fahrer\s*add)"]),
    ("driver_list", [r"(welche|wer\s*ist|liste|fahrer\s*list|fahrer\s*show)"]),
    ("export", [r"(export|csv|pdf|abrechnung|exportier)"]),
    ("assign_trip", [r"(weis\s*zu|zuweis|fahr(er|t)\s*#?\d)"]),
    ("escalate", [r"(problem|eskalation|offen|ungelöst)"]),
]

_DRIVER_KEYWORDS = [
    ("heute", [r"(heute|tag|fahrten|übersicht|tagesplan|was\s*(hab|steht))"]),
    ("pause", [r"(pause|kaffee|essen|toilette|durchatmen|kurz\s*(weg|raus))"]),
    ("ready", [r"(zurück|weiter|bereit|fertig\s*mit|pause\s*ende)"]),
    ("status", [r"(losfahren|angekommen|an\s*bord|abgesetzt|abschlie[ßs]en|fahr\s*los)"]),
    ("problem", [r"(problem|geht\s*nicht|nicht\s*da|unfall|stau|verspätung)"]),
]


def _keyword_match(text: str, patterns: list) -> str | None:
    """Fast regex keyword matching. Returns first matching intent or None."""
    t = text.lower().strip()
    for intent, pats in patterns:
        for p in pats:
            if re.search(p, t):
                return intent
    return None


async def _llm_classify(prompt_template: str, text: str) -> dict:
    """Send text to DeepSeek for intent classification. Returns parsed JSON or {}."""
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
                        {"role": "system", "content": prompt_template},
                        {"role": "user", "content": text},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 150,
                },
                timeout=10.0,
            )
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content.strip())
    except Exception:
        logger.warning("LLM NLU classification failed", exc_info=True)
        return {}


async def classify_chef(text: str) -> NluIntent:
    """Classify a chef message into an intent."""
    # 1. Keyword fast-path
    kw = _keyword_match(text, _CHEF_KEYWORDS)
    if kw:
        return NluIntent(intent=kw, confidence=0.80, raw_text=text)

    # 2. LLM
    result = await _llm_classify(CHEF_NLU_PROMPT, text)
    return NluIntent(
        intent=result.get("intent", "unknown"),
        confidence=result.get("confidence", 0.0),
        params=result.get("params", {}),
        raw_text=text,
    )


async def classify_driver(text: str) -> NluIntent:
    """Classify a driver message into an intent."""
    kw = _keyword_match(text, _DRIVER_KEYWORDS)
    if kw:
        return NluIntent(intent=kw, confidence=0.80, raw_text=text)

    result = await _llm_classify(DRIVER_NLU_PROMPT, text)
    return NluIntent(
        intent=result.get("intent", "unknown"),
        confidence=result.get("confidence", 0.0),
        raw_text=text,
    )


async def classify_patient(text: str) -> NluIntent:
    """Classify a patient message into an intent (delegates to booking NLU for book intent)."""
    result = await _llm_classify(PATIENT_NLU_PROMPT, text)
    return NluIntent(
        intent=result.get("intent", "unknown"),
        confidence=result.get("confidence", 0.0),
        params=result.get("params", {}),
        raw_text=text,
    )
