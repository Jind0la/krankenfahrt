# Implementierungsplan — Krankenfahrt System

## Übersicht

Das Projekt wird in 5 Phasen umgesetzt. Jede Phase besteht aus Kanban-Tasks, 
die von spezialisierten Worker-Profilen bearbeitet werden.

**Worker-Profile:**
| Profil | Rolle | Typische Tasks |
|--------|-------|---------------|
| `backend-eng` | Backend-Entwicklung | Bot-Handler, Core-Logik, API |
| `researcher` | Recherche & Analyse | Wettbewerb, Kassen-Abrechnung, Recht |
| `ops` | DevOps & Infrastruktur | Docker, Railway, Tests |
| `analyst` | Architektur & Design | Datenmodell-Review, API-Design |
| `strategist` | Business-Strategie | Pricing, GTM, Marktvalidierung |

**Task-Prioritäten:** 1 = kritisch, 2 = wichtig, 3 = nice-to-have

---

## Phase 0: Foundation (Tag 1-3)

### T0.1 — Projekt-Setup & CI [ops, Prio 1]
- pyproject.toml finalisieren (dependencies, dev-tools)
- Docker-Image bauen und testen
- Railway-Deployment konfigurieren
- GitHub-Repo einrichten (optional: GitLab)

### T0.2 — Datenmodell-Validierung [analyst, Prio 1]
- Tortoise-Modelle gegen reale Anforderungen prüfen
- Edge Cases: Storno, Umbuchung, Teilrückerstattung
- Index-Strategie für häufige Queries
- Migration-Strategie für Schema-Änderungen

### T0.3 — Rele-Fachrecherche: Kassen-Abrechnung [researcher, Prio 1]
- §302 SGB V: Technische Anforderungen DTA-Übermittlung
- Muster 4 digital: Stand 2026
- Abrechnungsdienstleister (ZAD, Noventi) und deren Schnittstellen
- Kosten/Nutzen: Selbst-abrechnen vs. outsourcen

### T0.4 — Voice-Infrastruktur [ops, Prio 2]
- faster-whisper in Docker integrieren
- Modell-Download und Caching
- Latenz-Test mit deutschen Sprachnachrichten
- Fallback wenn Whisper nicht verfügbar

---

## Phase 1: Core Bots (Tag 4-10)

### T1.1 — Patient-Bot: Buchung per Text [backend-eng, Prio 1]
- `/start`: Begrüßung, Registrierung (Name, Adresse, KK)
- NLU-Integration: DeepSeek für Buchungs-Extraktion
- `book`-Flow: Datum, Ziel, Rückfahrt abfragen → Trip anlegen
- Bestätigungs-Nachricht mit Zusammenfassung
- Edge Cases: Unvollständige Angaben, unbekannte Adressen

### T1.2 — Patient-Bot: Stammdaten & wiederkehrende Fahrten [backend-eng, Prio 1]
- Profil speichern/laden aus DB
- Standard-Adresse, Standard-Ziele merken
- „Jeden Mo/Mi/Fr 8:30 Dialyse" → RecurringTrip-Template
- Cron-inspirierter Generator: täglich Templates → konkrete Trips

### T1.3 — Patient-Bot: Status-Updates & Live-Tracking [backend-eng, Prio 1]
- Zustandsänderungen abonnieren → Push an Patient
- Live-Location: `bot.edit_message_live_location()`
- Erinnerungen: 24h + 1h vor Fahrt
- Storno-Flow: Patient kann eigene Fahrt stornieren

### T1.4 — Driver-Bot: Auftragsannahme & Status [backend-eng, Prio 1]
- Neuer Auftrag: Inline-Keyboard mit [✅ Annehmen] [❌ Ablehnen]
- Timeout nach 3 Min → Eskalation an Chef
- Status-Buttons: dynamisch basierend auf State-Machine
- `TRIGGER_MAP` aus state_machine.py nutzen
- Navigation-Link: Google Maps Deep-Link mit Zieladresse

### T1.5 — Driver-Bot: Tagesübersicht & Schicht [backend-eng, Prio 2]
- `/heute` — alle zugewiesenen Fahrten als Liste
- Morgendlicher Push mit Tagesplan (JobQueue)
- `/fertig` — Schicht beenden, alle offenen Fahrten eskalieren
- `/pause` — temporär keine neuen Aufträge (30 Min)

### T1.6 — Chef-Bot: Tages-Dashboard [backend-eng, Prio 1]
- `/dashboard` — alle Fahrten heute, farbcodiert
- Aktive Fahrer mit Status anzeigen
- Klick auf Fahrt → Details + Aktionen
- Manuelle Zuteilung: Fahrer auswählen → Fahrt zuweisen

### T1.7 — Chef-Bot: Fahrer- & Fahrzeugverwaltung [backend-eng, Prio 1]
- Neuen Fahrer anlegen: Name, Telegram-ID, Tel, P-Schein, Fahrzeug
- Fahrzeug anlegen: Kennzeichen, Typ, Kapazität
- Fahrer aktivieren/deaktivieren
- Arbeitszeiten + Tage konfigurieren

### T1.8 — Chef-Bot: Eskalations-Management [backend-eng, Prio 1]
- Eskalations-Trigger: Fahrer lehnt ab, Timeout, Problem-Meldung
- Chef bekommt Nachricht mit Kontext + Optionen
- Optionen: Fahrer wechseln, Patient informieren, Fahrt streichen
- Audit-Log in `trip_events`

### T1.9 — Chef-Bot: Abrechnungs-Export [backend-eng, Prio 2]
- CSV-Export: alle Fahrten in Zeitraum
- Felder: Datum, Patient, KK, Strecke, Typ, Status
- ReportLab-PDF: Muster-4-Vorlage befüllt
- Download per Telegram-File

### T1.10 — State Machine: Vollständige Integration [backend-eng, Prio 1]
- Alle `TRIP_TRANSITIONS` mit Callbacks verdrahten
- Validierung: nur erlaubte Übergänge
- Events loggen (`trip_events`)
- Status-Propagation an alle Bots

---

## Phase 2: Disposition Engine (Tag 11-16)

### T2.1 — Greedy-Engine: Produktionsreif [backend-eng, Prio 1]
- Fahrer-Nähe zum Abholort berechnen
- Constraint-Check: Fahrzeugtyp, P-Schein, Arbeitszeit
- Überlappungs-Check: keine Doppelbelegung
- Scoring: Distanz + Auslastung + Präferenzen

### T2.2 — Auto-Zuteilung ohne Chef-Intervention [backend-eng, Prio 1]
- Neue Fahrt → Engine läuft automatisch → Fahrer benachrichtigt
- Nur wenn kein Fahrer gefunden: Eskalation an Chef
- Config-Flag: `DISPATCH_MODE=greedy` (später =ortools)

### T2.3 — OSRM-Distanzmatrix (optional) [ops, Prio 3]
- OSRM Docker-Container deployen
- Distance-Matrix-Endpoint für alle Fahrer→Pickup-Kombinationen
- Fallback auf Haversine wenn OSRM nicht erreichbar

### T2.4 — OR-Tools-Integration [backend-eng, Prio 2]
- Pickup-and-Delivery with Time Windows modellieren
- Tägliches Optimierungsfenster (alle Fahrten + Fahrer)
- Vergleich Greedy vs. OR-Tools (Routenlänge, Pünktlichkeit)
- Plug-in-Interface: Dispatch-Engine austauschbar

---

## Phase 3: Polish & Testing (Tag 17-21)

### T3.1 — Integrationstests: Bot-Kommunikation [backend-eng, Prio 1]
- Patient bucht → Fahrer kriegt Auftrag → nimmt an → Status-Updates
- End-to-End mit Mock-Telegram-API
- Edge Cases: Timeout, Ablehnung, Storno

### T3.2 — Fehlerbehandlung & Resilienz [backend-eng, Prio 1]
- DeepSeek-API nicht erreichbar → Fallback (RegEx-basierte Extraktion)
- Datenbank-Connection-Loss → Retry mit Exponential Backoff
- Telegram-Rate-Limits → Queue + Retry
- Graceful Shutdown

### T3.3 — Logging & Monitoring [ops, Prio 2]
- structlog-Konfiguration (JSON für Railway)
- Key Metrics: Buchungen/Tag, Pünktlichkeit, Eskalationsrate
- Healthcheck-Endpoint für Railway
- Fehler-Alerting via Telegram an Chef

### T3.4 — Voice-Message-Integration [backend-eng, Prio 2]
- Sprachnachrichten von Fahrern transkribieren
- Intent-Erkennung aus transkribiertem Text
- „Bin in 5 Minuten da" → Status-Update setzen
- Fallback wenn kein Voice: reiner Text-Mode

### T3.5 — DSGVO-Audit & Datenschutz [researcher, Prio 2]
- Datenklassifikation: was sind personenbezogene Daten?
- Speicherorte: SQLite, Telegram (Transit)
- Löschkonzept: automatische Löschung nach X Tagen
- Auftragsverarbeitungsvertrag (AVV) Vorlage

---

## Phase 4: Launch & Scale (Tag 22+)

### T4.1 — Pilot-Betrieb mit 1-2 echten Fahrern [ops, Prio 1]
- Railway-Deployment finalisieren
- Onboarding-Flow für erste Fahrer
- Feedback-Schleife: Was fehlt? Was nervt?

### T4.2 — Business-Modell & Pricing [strategist, Prio 2]
- Pricing-Tiers: Start (bis 5 Fahrer), Wachstum (bis 15), Flotte (bis 50)
- Vergleich mit DMRZ, ZADTools, SanDispo
- RoI-Rechnung für Kunden

### T4.3 — Multi-Tenancy-Architektur [analyst, Prio 3]
- Eine Instanz pro Kunde vs. mandantenfähige DB
- Telegram-Bot-Factory: automatisch neue Bots pro Kunde
- Kosten-Implikationen beider Ansätze
