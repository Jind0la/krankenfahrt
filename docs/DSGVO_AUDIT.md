# DSGVO-Audit & Datenschutzbericht — Moradbakhti-KI (Krankenfahrt)

**Zweck:** Synthese-Audit der drei Teilanalysen Datenklassifikation, Löschkonzept und
AVV-Muster zu einer konsolidierten DSGVO-Compliance-Bewertung. Dieser Bericht prüft die
drei Quelldokumente auf Vollständigkeit, Konsistenz und identifiziert verbleibende
Lücken.

**Stand:** 06.06.2026
**Verantwortlicher:** Moradbakhti-KI (siehe Impressum in `config.py`)
**System:** Krankenfahrt — AI-First Medical Transport Dispatch (v0.3.0)
**Grundlage:**
- `docs/DATENKLASSIFIKATION.md` v1.0 (380 Zeilen, 51 Datenfelder)
- `docs/LOESCHKONZEPT.md` v1.0 (917 Zeilen, 14 Löschklassen, 11 autom. Regeln)
- `docs/AVV_Auftragsverarbeitungsvertrag_Muster.md` v1.0 (470 Zeilen, 11 §§ + 3 Anlagen)
- `docs/REQUIREMENTS_EDGE_CASES.md` (Datenmodell-Kontext)

**Nächste Überprüfung:** 06.12.2026 (6-Monats-Rhythmus)

---

## 1. Executive Summary

### 1.1 Gesamtbewertung

| Dimension | Status | Bewertung |
|-----------|--------|-----------|
| **Dateninventar** | ✅ Vollständig | 51 Datenfelder in 8 Tabellen + 8 externe Verarbeitungskategorien klassifiziert |
| **Sensitivitätsmodell** | ✅ Angemessen | 4-Stufen-Modell (S0–S3) mit Art. 9 DSGVO-Ausrichtung |
| **Löschkonzept** | ✅ Strukturiert | 14 Löschklassen nach DIN 66398, 11 automatisierte Regeln, 5 manuelle Trigger |
| **AVV-Rahmen** | ✅ Vorhanden | Art. 28 DSGVO-konformes Muster mit 11 §§ + 3 Anlagen, alle Pflichtinhalte abgedeckt |
| **Implementierung** | 🔴 Kritisch | Keine der identifizierten Maßnahmen umgesetzt — nur Konzeptphase |
| **Drittlandtransfer** | 🔴 Kritisch | DeepSeek (China) und Telegram (UAE) ohne Rechtsgrundlage |
| **Einwilligungsmanagement** | 🔴 Fehlend | Keine Consent-Felder im Datenmodell, keine Datenschutzerklärung |

**Fazit:** Die Dokumentation ist auf einem guten konzeptionellen Stand — alle drei
Teildokumente sind fachlich fundiert, rechtlich sauber referenziert und untereinander
konsistent. Die **Umsetzungslücke** ist jedoch erheblich: Die dokumentierten Maßnahmen
existieren ausschließlich auf Papier. Ohne Implementierung der P1-Maßnahmen ist das
System **nicht DSGVO-konform** und darf keine echten Patientendaten verarbeiten.

### 1.2 Wichtigste Findings (Top 5)

| # | Finding | Schwere | Quelle | Maßnahme |
|---|---------|---------|--------|----------|
| F1 | Drittlandtransfer DeepSeek (China) + Telegram (UAE) ohne Rechtsgrundlage — S3-Gesundheitsdaten fließen in Länder ohne Angemessenheitsbeschluss | 🔴 KRITISCH | DATENKLASSIFIKATION §6.1, LOESCHKONZEPT §6.1, AVV §4 | Migration zu EU-LLM + EU-Messaging ODER Art. 49(1)(a)-Einwilligung |
| F2 | Keine Trennung klinischer und Abrechnungsdaten — Art. 17 DSGVO Löschung unmöglich ohne Verletzung von §302 SGB V | 🔴 KRITISCH | DATENKLASSIFIKATION §6.2, LOESCHKONZEPT §5.1 | Pseudonymisierungs-Stufenmodell implementieren oder DB-Splitting |
| F3 | Keine Einwilligungsverwaltung — Art. 6(1)(a)/Art. 9(2)(h) DSGVO scheitern an fehlender Dokumentation | 🔴 KRITISCH | DATENKLASSIFIKATION §6.3, LOESCHKONZEPT REGEL-09 | Consent-Felder + Datenschutzerklärung implementieren (P1) |
| F4 | Keine Log-Rotation — structlog speichert unbefristet JSON-Logs mit Patientennamen | 🟠 HOCH | DATENKLASSIFIKATION §6.4, LOESCHKONZEPT REGEL-08 | 30-Tage-Log-Rotation (P1, 2h Aufwand) |
| F5 | GPS-Daten nach Fahrtende nicht genullt — potenzielle Bewegungsprofil-Erstellung | 🟠 MITTEL | DATENKLASSIFIKATION §6.5, LOESCHKONZEPT REGEL-06 | `driver_location_* = NULL` bei `complete_trip()` (P1, 0.5h) |

---

## 2. Dokumenten-Cross-Reference

### 2.1 Abdeckungsmatrix

| DSGVO-Anforderung | DATENKLASSIFIKATION | LOESCHKONZEPT | AVV-MUSTER | Bewertung |
|--------------------|--------------------|---------------|-----------|-----------|
| **Art. 5 — Grundsätze** | ✅ Zweckbindung, Datenminimierung dokumentiert | ✅ Speicherbegrenzung operationalisiert | — | Vollständig |
| **Art. 6 — Rechtmäßigkeit** | ✅ 4 Rechtsgrundlagen pro Feld dokumentiert | ✅ Ausnahmen in §1.2 | ✅ Verantwortlicher muss Rechtsgrundlage sicherstellen (§6) | Vollständig |
| **Art. 9 — Besondere Kategorien** | ✅ S3-Klassifikation für Gesundheitsdaten | ✅ S3-Löschklassen priorisiert | ✅ §9 mit zusätzlichen Schutzmaßnahmen | Vollständig |
| **Art. 12–22 — Betroffenenrechte** | — (Konzept in §9) | ✅ Art. 17 (Löschung), 19 (Mitteilung), 20 (Export) | ✅ §3.5 verpflichtet AV zur Unterstützung | Auskunft (Art. 15), Berichtigung (Art. 16) fehlen |
| **Art. 17 — Recht auf Löschung** | ✅ Löschstrategie pro Feld | ✅ 4-Schritt-Prozess + gestufte Löschung | ✅ §7 regelt Rückgabe/Löschung durch AV | Vollständig |
| **Art. 25 — Privacy by Design** | ✅ Datenminimierung pro Feld begründet | ✅ Default-Löschregeln | ✅ TOM-Anlage 2 §4.3 | Vollständig |
| **Art. 28 — Auftragsverarbeitung** | ✅ Drittland-Risiken identifiziert | ✅ AVV-Löschpflichten §6 | ✅ 11 §§ + 3 Anlagen, alle Pflichtinhalte | Vollständig (Muster) |
| **Art. 30 — VVT** | — (als Grundlage geeignet) | ✅ Löschfristen dokumentiert | ✅ §3.1 verpflichtet AV | VVT selbst fehlt als separates Dokument |
| **Art. 32 — TOM** | — | ✅ Löschmethoden §8.1, secure_delete | ✅ Anlage 2 mit Checkliste (39 Items) | TOM-Dokumentation fehlt als separates Dokument |
| **Art. 33/34 — Data Breach** | — | ✅ §4.5 Incident Response | ✅ §3.6 (24h-Meldepflicht) | Incident-Response-Plan fehlt |
| **Art. 35 — DSFA** | — | — | ✅ §3.5(b) verpflichtet AV zur Unterstützung | DSFA selbst fehlt |
| **Art. 44–49 — Drittlandtransfer** | ✅ Identifiziert als schwerwiegende Lücke | ✅ Detaillierte Risikoanalyse §6 | ✅ §4 regelt Voraussetzungen, Anlage 3 | Mapping auf konkrete Transfers fehlt |
| **§302 SGB V — Abrechnung** | ✅ Fristen dokumentiert | ✅ LK-S3-10Y-BIL | — | Vollständig |
| **DIN 66398 — Löschkonzept** | — | ✅ Löschklassen-Modell + Matrix | — | Vollständig |

### 2.2 Konsistenz-Checks

| Prüfpunkt | DATENKLASSIFIKATION | LOESCHKONZEPT | Konsistent? |
|-----------|--------------------|---------------|-------------|
| Anzahl Datenfelder | 51 | 51 („alle 51 Datenfelder aus DATENKLASSIFIKATION.md") | ✅ Ja |
| Anzahl Löschklassen | — (vorgelagert) | 14 | ✅ Deckt alle Felder ab |
| S3-Datenkategorien | 13 Felder + 4 externe | LK-S3-10Y-EV + LK-S3-10Y-BIL + LK-S3-0D-* | ✅ Ja |
| Aufbewahrungsfrist Patienten (klinisch) | 10 Jahre (§630f BGB) | 10 Jahre (§630f BGB) | ✅ Ja |
| Aufbewahrungsfrist Abrechnung | 10 Jahre (§302 SGB V) | 10 Jahre (§302 SGB V) | ✅ Ja |
| Aufbewahrungsfrist Fahrerdaten | 3 Jahre (§195 BGB) | 3 Jahre (§195 BGB) | ✅ Ja |
| Aufbewahrungsfrist Logs | 30 Tage | 30 Tage | ✅ Ja |
| DeepSeek-Risiko | 🔴 Schwerwiegend | 🔴 Nicht kontrollierbar | ✅ Ja |
| Telegram-Risiko | 🔴 Schwerwiegend | 🔴 Nicht kontrollierbar | ✅ Ja |
| Sofortmaßnahmen-Anzahl | 8 | 13 (Roadmap) | ⚠️ Unterschiedliche Granularität — Löschkonzept hat detailliertere Roadmap |
| Gesamtaufwand Implementierung | — (keine Summe) | ~47.6h | — (Löschkonzept spezifischer) |

### 2.3 Gefundene Inkonsistenzen

| # | Inkonsistenz | Dokument A | Dokument B | Empfehlung |
|---|-------------|-----------|-----------|------------|
| I1 | **Anzahl Sofortmaßnahmen**: DATENKLASSIFIKATION listet 8, LOESCHKONZEPT hat 13 Roadmap-Einträge | DATENKLASSIFIKATION §7 | LOESCHKONZEPT §9.2 | LOESCHKONZEPT als führend betrachten (detaillierter). DATENKLASSIFIKATION §7 auf LOESCHKONZEPT verweisen lassen |
| I2 | **Datenexport-Flow**: DATENKLASSIFIKATION beschreibt Abrechnungs-CSV über Telegram-Upload | LOESCHKONZEPT erwähnt CSV-Export nur als Löschobjekt | AVV §7 verlangt strukturiertes Format | Widerspruch: CSV mit S3-Daten über Telegram (UAE) zu senden ist unzulässig. Muss im Audit adressiert werden |
| I3 | **Löschklasse LK-S2-2Y-AZG**: LOESCHKONZEPT definiert sie, DATENKLASSIFIKATION führt §16 ArbZG korrekt auf | DATENKLASSIFIKATION §5 | LOESCHKONZEPT LK-S2-2Y-AZG | ✅ Inhaltlich konsistent, aber LOESCHKONZEPT spezifischer (REGEL-05 mit SQL) |
| I4 | **AVV-Anlagen**: AVV §11 nennt 3 Anlagen, aber Anlage 1 enthält Platzhalter und ist nicht für konkrete Auftragsverarbeiter ausgefüllt | AVV Anlage 1 | DATENKLASSIFIKATION §3 (Datenflüsse) | AVV muss für DeepSeek, Telegram, Hosting-Provider konkret ausgefüllt werden |

---

## 3. Compliance-Status pro DSGVO-Artikel

### 3.1 Art. 5 — Grundsätze der Datenverarbeitung

| Prinzip | Status | Nachweis |
|---------|--------|----------|
| Rechtmäßigkeit (lit. a) | 🟡 Konzept | Rechtsgrundlagen pro Feld in DATENKLASSIFIKATION §8 dokumentiert. Aber: Einwilligung fehlt praktisch |
| Zweckbindung (lit. b) | ✅ Erfüllt | Transport-Disposition als klarer Zweck definiert |
| Datenminimierung (lit. c) | ✅ Konzept | DATENKLASSIFIKATION begründet Notwendigkeit pro Feld. LK-S3-0D-TEMP sofortige Löschung implementiert |
| Richtigkeit (lit. d) | 🟡 Konzept | Kein expliziter Prozess für Art. 16 DSGVO (Berichtigung) |
| Speicherbegrenzung (lit. e) | ✅ Konzept | 14 Löschklassen mit konkreten Fristen, 11 automatisierte Regeln |
| Integrität/Vertraulichkeit (lit. f) | 🟡 Konzept | AVV Anlage 2 definiert TOM, secure_delete PRAGMA geplant |
| Rechenschaftspflicht (Abs. 2) | 🟡 Konzept | Löschprotokoll-Tabelle definiert, aber nicht implementiert |

### 3.2 Art. 9 — Besondere Kategorien (Gesundheitsdaten)

| Anforderung | Status | Nachweis |
|------------|--------|----------|
| Verarbeitungsverbot mit Ausnahmen | ✅ Konzept | Art. 9(2)(h) DSGVO als Rechtsgrundlage für alle S3-Felder |
| Erforderlichkeit für Gesundheitsdienstleistung | ✅ Belegt | Krankentransport = Gesundheitsdienstleistung i.S.d. Art. 9(2)(h) |
| Zusätzliche Schutzmaßnahmen | 🟡 Konzept | AVV §9 definiert, aber nicht implementiert |
| §22 BDSG (nationale Öffnungsklausel) | ✅ Berücksichtigt | In DATENKLASSIFIKATION §1 referenziert |

### 3.3 Art. 17 — Recht auf Löschung

| Anforderung | Status | Nachweis |
|------------|--------|----------|
| Löschpflicht | ✅ Konzept | 4-Schritt-Prozess, gestufte Löschung, 1-Monats-Frist |
| Ausnahmen (Abs. 3) | ✅ Dokumentiert | §302 SGB V, §147 AO, §630f BGB in §1.2 LOESCHKONZEPT |
| Technische Umsetzung | 🔴 Fehlt | Keine Implementierung — nur Konzept |
| Mitteilungspflicht (Art. 19) | ✅ Konzept | Standardisiertes Bestätigungsschreiben §7.4 LOESCHKONZEPT |

### 3.4 Art. 28 — Auftragsverarbeitung

| Anforderung | Status | Nachweis |
|------------|--------|----------|
| Schriftlicher Vertrag | ✅ Muster | AVV mit 11 §§ + 3 Anlagen |
| Pflichtinhalte (Abs. 3) | ✅ Alle | Gegenstand, Dauer, Art/Zweck, Datenkategorien, Betroffene, Pflichten |
| Weisungsgebundenheit | ✅ Geregelt | AVV §2 |
| TOM-Nachweis | ✅ Checkliste | AVV Anlage 2 (39 Items) |
| Subunternehmer | ✅ Geregelt | AVV §5 mit Genehmigungsvorbehalt |
| **Mit DeepSeek abgeschlossen?** | 🔴 Nein | Kein AVV existent |
| **Mit Telegram abgeschlossen?** | 🔴 Nein | Kein AVV existent |
| **Mit Hosting-Provider?** | 🔴 Nein | Kein AVV existent |

### 3.5 Art. 30 — Verzeichnis von Verarbeitungstätigkeiten (VVT)

| Anforderung | Status | Nachweis |
|------------|--------|----------|
| Eigenes VVT | 🟡 Vorbereitet | DATENKLASSIFIKATION enthält alle Pflichtangaben (Datenkategorien, Zwecke, Fristen, Empfänger) — aber kein formales VVT-Dokument |
| AV-VVT (Art. 30 Abs. 2) | 🟡 Geregelt | AVV §3.1 verpflichtet AV zur Führung |

### 3.6 Art. 32 — Sicherheit der Verarbeitung

| Anforderung | Status | Nachweis |
|------------|--------|----------|
| TOM-Dokumentation | ✅ Checkliste | AVV Anlage 2 mit 39 Items |
| Verschlüsselung | 🟡 Teilweise | `secure_delete` PRAGMA geplant. Transport-Verschlüsselung nicht dokumentiert |
| Pseudonymisierung | ✅ Konzept | Gestuftes Verfahren in LOESCHKONZEPT §5.1 |
| Incident Response | 🟡 Konzept | LOESCHKONZEPT §4.5, AVV §3.6 — aber kein formaler IR-Plan |

### 3.7 Art. 35 — Datenschutz-Folgenabschätzung (DSFA)

| Anforderung | Status | Nachweis |
|------------|--------|----------|
| DSFA-Pflicht | 🟡 Auslöser identifiziert | Art. 9 + Drittlandtransfer + systematische Überwachung = DSFA-Pflicht nach Art. 35(3) |
| DSFA durchgeführt | 🔴 Nein | Nicht vorhanden |
| AVV-Verpflichtung | ✅ Geregelt | AVV §3.5(b) verpflichtet AV zur Unterstützung |

### 3.8 Art. 44–49 — Drittlandtransfers

| Anforderung | Status | Nachweis |
|------------|--------|----------|
| DeepSeek (China) | 🔴 Kritisch | Kein Angemessenheitsbeschluss, keine SCCs, keine Einwilligung |
| Telegram (UAE) | 🔴 Kritisch | Kein Angemessenheitsbeschluss, keine SCCs, keine Einwilligung |
| Dokumentation | ✅ Vollständig | DATENKLASSIFIKATION §6.1, LOESCHKONZEPT §6, AVV §4 + Anlage 3 |
| Art. 49(1)(a) Einwilligung | 🟡 Konzept | Als Weg dokumentiert, aber nicht implementiert |

---

## 4. Risikomatrix (Konsolidiert)

### 4.1 Kritische Risiken (🔴 — muss vor Produktivbetrieb gelöst sein)

| ID | Risiko | Eintrittsw. | Schaden | DSGVO-Verstoß | Maßnahme |
|----|--------|------------|---------|---------------|----------|
| R1 | **DeepSeek verarbeitet S3-Daten ohne Rechtsgrundlage** | Hoch (tritt bei JEDER Patientennachricht ein) | Sehr hoch (Bußgeld bis 20 Mio. EUR) | Art. 44–49 DSGVO | Migration EU-LLM ODER Art. 49(1)(a) Einwilligung + AVV mit SCCs |
| R2 | **Telegram speichert Chat-Verlauf mit S3-Daten in UAE** | Hoch (bei jeder Interaktion) | Hoch (Bußgeld + Betroffenenrechte nicht durchsetzbar) | Art. 44–49, Art. 17 DSGVO | Migration EU-Messaging ODER informierte Einwilligung |
| R3 | **Keine Einwilligung dokumentiert** | Sicher (aktuell gar keine) | Sehr hoch (Verarbeitung ohne Rechtsgrundlage) | Art. 6(1)(a), Art. 9(2)(h) | Consent-Felder + Datenschutzerklärung (P1) |
| R4 | **Löschung nach Art. 17 nicht möglich wegen §302 SGB V-Konflikt** | Mittel (bei jedem Löschantrag) | Hoch (Nichterfüllung Betroffenenrecht) | Art. 17 DSGVO | Gestufte Löschung implementieren (Sprint 1) |

### 4.2 Hohe Risiken (🟠 — muss kurzfristig adressiert werden)

| ID | Risiko | Eintrittsw. | Schaden | Maßnahme |
|----|--------|------------|---------|----------|
| R5 | **Logs mit Patientennamen unbegrenzt gespeichert** | Sicher (aktuell so) | Mittel | Log-Rotation (P1, 2h) |
| R6 | **SQLite-Daten forensisch wiederherstellbar** | Mittel | Hoch | `PRAGMA secure_delete = ON` + `VACUUM` (P1, 0.1h) |
| R7 | **GPS-Daten nach Fahrtende persistent** | Hoch | Mittel | `driver_location_* = NULL` bei Fahrtende (P1, 0.5h) |
| R8 | **CSV mit vollen Patientendaten über Telegram versendet** | Mittel | Hoch | Verschlüsselter Export-Kanal statt Telegram-File-Upload |
| R9 | **Keine DSFA durchgeführt** | Sicher (nicht vorhanden) | Hoch | DSFA nachholen (P2) |

### 4.3 Mittlere Risiken (🟡)

| ID | Risiko | Maßnahme |
|----|--------|----------|
| R10 | TripEvent.message als unkontrollierter S3-Freitext | P3: Content-Filter oder strukturierte Events |
| R11 | Kein formaler Incident-Response-Plan | P2: IR-Plan nach BSI IT-Grundschutz |
| R12 | Kein VVT-Dokument | P2: VVT aus DATENKLASSIFIKATION extrahieren |
| R13 | AVV-Platzhalter nicht ausgefüllt | P2: Konkrete AVVs mit DeepSeek, Telegram, Hosting-Provider |

---

## 5. Implementierungs-Roadmap (Konsolidiert)

### 5.1 Abgleich der Maßnahmenkataloge

| Quelle | Anzahl Maßnahmen | Fokus |
|--------|-----------------|-------|
| DATENKLASSIFIKATION §7 | 8 Sofortmaßnahmen | Klassifikation + Consent |
| LOESCHKONZEPT §9.2 | 13 Roadmap-Einträge | Löschung + Datenmodell |
| AVV-Muster | Auszufüllende Anlagen | Verträge mit Auftragsverarbeitern |
| **Dieser Audit** | **18 Maßnahmen (nachfolgend)** | **Konsolidiert + priorisiert** |

### 5.2 Sprint 1 — Produktionsblockierend (P1, ~10.6h)

Diese Maßnahmen MÜSSEN vor Verarbeitung echter Patientendaten umgesetzt sein:

| # | Maßnahme | Aufwand | Betroffenes Dokument | Querverweis |
|---|----------|---------|---------------------|-------------|
| 1 | **Einwilligungs-Management implementieren** — Consent-Felder (`consent_given_at`, `consent_version`, `consent_withdrawn_at`) zu `patients` hinzufügen | 2h | DATENKLASSIFIKATION §6.3, LOESCHKONZEPT §9.2 #1 | R3 |
| 2 | **Datenschutzerklärung verfassen** — mit explizitem Hinweis auf DeepSeek/China und Telegram/UAE. Bot-Onboarding mit Consent-Flow | 4h | DATENKLASSIFIKATION §7 #2 | R1, R2, R3 |
| 3 | **Datenmodell-Erweiterung für Löschung** — `deletion_requested_at`, `data_retention_until`, `pseudonymized_at`, `data_restricted` | 1h | LOESCHKONZEPT §9.2 #1 | R4 |
| 4 | **`deletion_log` Tabelle erstellen** — und in DB-Schema aufnehmen | 1h | LOESCHKONZEPT §7.1 | — |
| 5 | **`PRAGMA secure_delete = ON`** in DB-Init setzen | 0.1h | LOESCHKONZEPT §8.2 | R6 |
| 6 | **Log-Rotation 30 Tage** — Cron-Job oder logrotate | 2h | LOESCHKONZEPT REGEL-08 | R5 |
| 7 | **GPS-Nullung bei Fahrtende** — `driver_location_* = NULL` in `complete_trip()` | 0.5h | LOESCHKONZEPT REGEL-06 | R7 |

### 5.3 Sprint 2 — Vor Skalierung (P2, ~27h)

| # | Maßnahme | Aufwand | Querverweis |
|---|----------|---------|-------------|
| 8 | **Cron-Skript `scripts/deletion_cron.py`** — Alle 11 automatisierten Löschregeln (REGEL-01 bis REGEL-11) | 4h | R4 |
| 9 | **LLM-Migration evaluieren** — DeepSeek China → EU-Alternative (Mistral EU, Aleph Alpha, lokales Ollama) | 8h | R1 |
| 10 | **Manueller Löschworkflow** — Admin-Interface für Patienten-Löschanträge (4-Schritt-Prozess) | 4h | R4 |
| 11 | **Datenexport-Funktion (Art. 20 DSGVO)** — JSON-Export vor Löschung | 2h | — |
| 12 | **Backup-Rotation** — Automatische Löschung alter Backups (10-Jahres-Frist) | 2h | — |
| 13 | **Export-Datei-Bereinigung** — Löschung alter CSVs/PDFs | 1h | R8 |
| 14 | **AVV mit DeepSeek abschließen** (wenn Migration nicht möglich) — mit EU-SCCs | — | R1 |
| 15 | **AVV mit Hosting-Provider abschließen** | — | R13 |
| 16 | **DSFA durchführen** — Datenschutz-Folgenabschätzung nach Art. 35 DSGVO | 6h | R9 |

### 5.4 Sprint 3 — Optimierung (P3, ~20h)

| # | Maßnahme | Aufwand | Querverweis |
|---|----------|---------|-------------|
| 17 | **Jährlicher Lösch-Audit** — Automatisierter Report | 4h | — |
| 18 | **Telegram-Migration evaluieren** — EU-Messaging (Matrix/Element) | 16h | R2 |

---

## 6. AVV-Pflichtenmatrix

### 6.1 Auftragsverarbeiter, mit denen ein AVV geschlossen werden MUSS

| Auftragsverarbeiter | Dienstleistung | Datenkategorien | Drittland? | AVV-Status | Dringlichkeit |
|--------------------|----------------|----------------|-----------|------------|--------------|
| **DeepSeek** (深度求索) | NLU-Extraktion aus Patientennachrichten | S3: Gesundheitsdaten, Name, Adresse, Behandlungskontext | Ja — China (kein Angemessenheitsbeschluss) | 🔴 Kein AVV | P1 |
| **Telegram** (Telegram FZ-LLC) | Messaging-Infrastruktur | S3: Chat-Nachrichten, Sprachnachrichten, telegram_id | Ja — UAE (kein Angemessenheitsbeschluss) | 🔴 Kein AVV | P1 |
| **Hosting-Provider** | Server-Hosting der Anwendung | S1–S3: Komplette Datenbank, Logs, Backups | Abhängig von Provider | 🔴 Kein AVV | P2 |
| **faster-whisper** | Lokale Sprach-zu-Text-Transkription | S3: Sprachaufnahmen (temporär) | Nein — lokal | ✅ Kein AVV nötig (kein Auftragsverarbeiter, lokale Verarbeitung) | — |

### 6.2 Für DeepSeek spezifisch erforderliche AVV-Klauseln

Zusätzlich zu den Standardklauseln des AVV-Musters:

1. **§4 Drittlandtransfer:** Art. 46 DSGVO-Garantien (EU-SCCs Durchführungsbeschluss 2021/914)
2. **§7 Datenrückgabe/Löschung:** Explizite Löschschnittstelle (derzeit nicht vorhanden!)
3. **§9 Gesundheitsdaten:** Verbot der Nutzung für Modell-Training (Art. 9 DSGVO)
4. **Anlage 1:** Präzise Beschreibung: welche Prompts, welche extrahierten Daten
5. **Anlage 3:** China als Drittland mit SCCs dokumentieren

### 6.3 Pragmatische Empfehlung

Die AVV-Situation mit DeepSeek und Telegram ist faktisch nicht lösbar:
- DeepSeek hat kein bekanntes Data Processing Agreement für EU-Kunden
- DeepSeek hat keine Löschschnittstelle
- Telegram erlaubt keine nachträgliche Löschung von Chat-Verläufen durch Bots

**Empfohlen:** Statt AVV-Verhandlungen mit nicht-kooperativen Drittland-Anbietern:
1. DeepSeek → Migration zu EU-LLM (Mistral EU über API, Aleph Alpha, oder lokales Ollama-Modell)
2. Telegram → Evaluierung Matrix/Element mit E2EE oder Signal Bot API

---

## 7. Audit-Checkliste (Betriebsbereitschaft)

Diese Checkliste muss VOLLSTÄNDIG erfüllt sein, bevor das System echte Patientendaten
verarbeiten darf:

### 7.1 Formelle Anforderungen

- [ ] **Datenschutzerklärung** existiert und ist Patienten zugänglich
- [ ] **Einwilligung** wird aktiv eingeholt und dokumentiert (`consent_given_at`)
- [ ] **DSFA** (Datenschutz-Folgenabschätzung) ist durchgeführt
- [ ] **VVT** (Verzeichnis von Verarbeitungstätigkeiten) ist erstellt
- [ ] **DSB** (Datenschutzbeauftragter) ist benannt (sofern nach §38 BDSG erforderlich: >20 Personen mit automatisierter Verarbeitung)
- [ ] **AVV mit DeepSeek** ist abgeschlossen ODER DeepSeek wurde durch EU-LLM ersetzt
- [ ] **AVV mit Hosting-Provider** ist abgeschlossen

### 7.2 Technische Anforderungen

- [ ] `consent_given_at`, `consent_version`, `consent_withdrawn_at` Felder existieren
- [ ] `deletion_requested_at`, `data_retention_until`, `pseudonymized_at`, `data_restricted` Felder existieren
- [ ] `deletion_log` Tabelle existiert
- [ ] `PRAGMA secure_delete = ON` ist aktiv
- [ ] Log-Rotation 30 Tage ist aktiv
- [ ] GPS-Daten werden bei Fahrtende genullt
- [ ] `scripts/deletion_cron.py` läuft (alle 11 Regeln)
- [ ] Backup-Rotation ist konfiguriert
- [ ] Sprachaufnahmen werden nach Transkription gelöscht (bereits ✅)
- [ ] Telegram-Nachrichten werden nicht persistiert (bereits ✅)

### 7.3 Organisatorische Anforderungen

- [ ] Prozess für manuelle Löschanträge ist dokumentiert und getestet
- [ ] Incident-Response-Plan existiert
- [ ] Mitarbeiter sind auf Datengeheimnis verpflichtet
- [ ] Regelmäßige Datenschutz-Schulungen sind etabliert
- [ ] Eskalationspfad für fehlgeschlagene Löschungen ist definiert

---

## 8. Datenfluss-Datenschutzbewertung

### 8.1 Buchungs-Flow (Sprachnachricht) — Risikobewertung

```
Patient → Telegram (UAE) 🔴 → Voice Message (.ogg temp, lokal ✅) → faster-whisper (lokal ✅)
→ Text → DeepSeek API (China) 🔴 → NLU JSON → Trip in SQLite (lokal ✅)
```

| Schritt | DSGVO-Status | Risiko |
|---------|-------------|--------|
| Telegram-Transport | 🔴 Drittland ohne Rechtsgrundlage | S3-Daten in UAE |
| Voice-zu-Text (lokal) | ✅ Kein Drittlandtransfer | — |
| DeepSeek NLU | 🔴 Drittland ohne Rechtsgrundlage | S3-Daten in China |
| SQLite-Speicherung | ✅ Lokal, Pseudonymisierungskonzept vorhanden | — |

### 8.2 Abrechnungs-Flow — Risikobewertung

```
Chef → /export → CSV mit Patientennamen + Versichertennummern → Telegram File Upload 🔴
```

⚠️ **Dieser Flow ist in der aktuellen Form unzulässig:** S3-Daten (Patientennamen +
Versichertennummern) werden unverschlüsselt über Telegram (UAE) übertragen.

**Sofortmaßnahme (Workaround bis Sprint 2):** Export via verschlüsseltem Kanal (SFTP,
verschlüsselte E-Mail, oder lokaler Download).

### 8.3 Live-Tracking Flow — Risikobewertung

```
Driver → Telegram (UAE) 🔴 → driver_location_lat/lon → Notification an Patient
```

Das Live-Tracking selbst ist zweckgebunden (Art. 6(1)(b) DSGVO) und die GPS-Daten werden
nach Fahrtende genullt (nach Implementierung). Das Risiko liegt im Transportweg über
Telegram (UAE).

---

## 9. Quellenverzeichnis

### 9.1 Interne Quelldokumente

| Dokument | Zeilen | Version |
|----------|--------|---------|
| `docs/DATENKLASSIFIKATION.md` | 380 | v1.0, 06.06.2026 |
| `docs/LOESCHKONZEPT.md` | 917 | v1.0, 06.06.2026 |
| `docs/AVV_Auftragsverarbeitungsvertrag_Muster.md` | 470 | v1.0, 06.06.2026 |
| `docs/REQUIREMENTS_EDGE_CASES.md` | 376 | 06.06.2026 |

### 9.2 Rechtsgrundlagen

| Norm | Anwendung |
|------|-----------|
| **DSGVO** (EU 2016/679) | Gesamter Rechtsrahmen: Art. 5, 6, 9, 12–22, 25, 28, 30, 32, 33/34, 35, 44–49, 82 |
| **BDSG** | §22 (Art. 9-Öffnungsklausel), §38 (DSB-Pflicht) |
| **SGB V** | §302 (Abrechnung GKV), §304 (Aufbewahrung), §67 (Sozialdaten) |
| **SGB X** | §84 (Löschung Sozialdaten) |
| **AO** | §147 (Steuerliche Aufbewahrung 10 Jahre) |
| **HGB** | §257 (Handelsrechtliche Aufbewahrung 10 Jahre) |
| **BGB** | §195 (Regelverjährung 3 Jahre), §199 (Personenschäden 30 Jahre), §630f (Patientenakte 10 Jahre) |
| **ArbZG** | §16 (Arbeitszeitdokumentation 2 Jahre) |
| **PBefG** | Fahreignung (P-Schein) |
| **DIN 66398 / ISO/IEC 27555:2025-09** | Löschkonzept-Standard |
| **EU-SCC 2021/915** | Standardvertragsklauseln für Drittlandtransfers |

### 9.3 Externe Referenzen

- BfDI-Mustervereinbarung zur Auftragsverarbeitung v2.1
- WKO-Mustervertrag Auftragsverarbeitung
- activeMind AG AV-Vertrag Muster
- BayLfD: Orientierungshilfe Löschung
- cortina-consult: Löschkonzept DSGVO
- robin-data: Löschkonzept DSGVO
- isico: Löschkonzept DIN 66398

---

## 10. Glossar

| Begriff | Definition |
|---------|-----------|
| **DSGVO** | Datenschutz-Grundverordnung (EU) 2016/679 |
| **BDSG** | Bundesdatenschutzgesetz (Deutschland) |
| **SGB V** | Sozialgesetzbuch V — Gesetzliche Krankenversicherung |
| **SGB X** | Sozialgesetzbuch X — Sozialdatenschutz |
| **AO** | Abgabenordnung (Steuerrecht) |
| **HGB** | Handelsgesetzbuch |
| **ArbZG** | Arbeitszeitgesetz |
| **BGB** | Bürgerliches Gesetzbuch |
| **PBefG** | Personenbeförderungsgesetz |
| **Art. 9 DSGVO** | Besondere Kategorien personenbezogener Daten (Gesundheitsdaten) |
| **Art. 17 DSGVO** | Recht auf Löschung ("Recht auf Vergessenwerden") |
| **Art. 28 DSGVO** | Auftragsverarbeiter |
| **Art. 35 DSGVO** | Datenschutz-Folgenabschätzung (DSFA) |
| **Art. 44–49 DSGVO** | Drittlandtransfer |
| **AVV** | Auftragsverarbeitungsvertrag (Data Processing Agreement) |
| **SCC** | Standardvertragsklauseln (Standard Contractual Clauses) |
| **DSB** | Datenschutzbeauftragter |
| **DSFA** | Datenschutz-Folgenabschätzung |
| **TOM** | Technische und organisatorische Maßnahmen |
| **VVT** | Verzeichnis von Verarbeitungstätigkeiten (Art. 30 DSGVO) |
| **LK** | Löschklasse nach DIN 66398 |
| **Muster-4** | Abrechnungsformular für Krankentransport nach §302 SGB V |
| **PHI** | Protected Health Information (HIPAA-Äquivalent, hier nicht direkt anwendbar) |

---

*Dokument erstellt am 06.06.2026 durch Synthese der drei Teilanalysen.*
*Zuletzt geprüft: 06.06.2026*
*Nächste Überprüfung: 06.12.2026 (6-Monats-Rhythmus)*

---

## Anhang A: Vollständige Findings-Liste (15 Findings)

| ID | Schwere | Kategorie | Finding | Quelle |
|----|---------|-----------|---------|--------|
| F1 | 🔴 KRITISCH | Drittlandtransfer | DeepSeek (China): Patientendaten ohne Rechtsgrundlage | DAT §6.1, LOE §6.1, AVV §4 |
| F2 | 🔴 KRITISCH | Drittlandtransfer | Telegram (UAE): Chat-Verlauf ohne Rechtsgrundlage | DAT §6.1, LOE §3.3/§6.2 |
| F3 | 🔴 KRITISCH | Datenmodell | Keine Trennung klinischer/Abrechnungsdaten | DAT §6.2 |
| F4 | 🔴 KRITISCH | Einwilligung | Keine Consent-Verwaltung implementiert | DAT §6.3, LOE REGEL-09 |
| F5 | 🟠 HOCH | Logs | Keine Log-Rotation, S3-Daten in Logs | DAT §6.4, LOE REGEL-08 |
| F6 | 🟠 HOCH | Forensik | SQLite-Daten ohne `secure_delete` wiederherstellbar | LOE §8.2 |
| F7 | 🟠 HOCH | Transport | CSV mit S3-Daten über Telegram exportiert | DAT §3.4, I2 |
| F8 | 🟠 HOCH | DSFA | Keine Datenschutz-Folgenabschätzung durchgeführt | Art. 35 DSGVO |
| F9 | 🟠 HOCH | IR-Plan | Kein formaler Incident-Response-Plan | LOE §4.5 |
| F10 | 🟡 MITTEL | GPS | GPS-Daten nach Fahrtende nicht genullt | DAT §6.5, LOE REGEL-06 |
| F11 | 🟡 MITTEL | VVT | Kein formales Verarbeitungsverzeichnis | Art. 30 DSGVO |
| F12 | 🟡 MITTEL | AVV-Umsetzung | AVV-Platzhalter nicht ausgefüllt, nicht unterzeichnet | AVV Anlagen 1–3 |
| F13 | 🟡 MITTEL | Betroffenenrechte | Art. 15 (Auskunft), Art. 16 (Berichtigung) nicht dokumentiert | — |
| F14 | 🟢 NIEDRIG | Datenqualität | TripEvent.message als unkontrollierter Freitext | DAT §6.7 |
| F15 | 🟢 NIEDRIG | Datenqualität | Telegram-ID als personenbezogenes Datum nicht in Auskunft dokumentiert | DAT §6.6 |

## Anhang B: Kennzahlen (KPIs) für DSGVO-Compliance

| KPI | Zielwert | Messmethode | Aktuell |
|-----|---------|-------------|---------|
| Automatische Löschquote | 100% fristgerecht | `deletion_log` Analyse | 0% (nicht implementiert) |
| Manuelle Löschanträge in Frist | 100% ≤ 30 Tage | `AVG(executed_at - requested_at)` | N/A |
| Fehlgeschlagene Löschungen | 0 | `deletion_errors WHERE resolved=FALSE` | N/A |
| GPS-Daten-Leakage | 0 aktive Datensätze | `COUNT(*) FROM trips WHERE actual_dropoff IS NOT NULL AND driver_location_lat IS NOT NULL` | Unbekannt |
| Einwilligungsquote | 100% der aktiven Patienten | `patients WHERE consent_given_at IS NOT NULL` | 0% |
| AVV-Abdeckung | 100% der Auftragsverarbeiter | Anzahl AVV / Anzahl AV | 0% |
| Log-Retention | ≤ 30 Tage | `MAX(age) FROM logs` | ∞ |
| DSGVO-Compliance-Status | Grün | Audit-Checkliste 100% erfüllt | Rot |
