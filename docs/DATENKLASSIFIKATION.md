# Datenklassifikation — Moradbakhti-KI (Krankenfahrt)

**Zweck:** Identifikation, Kategorisierung und Klassifikation aller personenbezogenen Daten,
die durch das Krankenfahrt-System verarbeitet werden. Dient als Grundlage für
DSGVO-Compliance, Datenminimierung und Löschkonzept.

**Stand:** 06.06.2026
**Verantwortlicher:** Moradbakhti-KI (siehe Impressum in `config.py`)
**System:** Krankenfahrt — AI-First Medical Transport Dispatch (v0.3.0)

---

## 1. Klassifikationssystem

Vierstufiges Sensitivitätsmodell, abgeleitet aus DSGVO Art. 9, BDSG §22 und
Branchenstandard (Censinet Healthcare Data Sensitivity Levels).

| Stufe | Bezeichnung | Definition | Schadenspotenzial bei Offenlegung |
|-------|-------------|-----------|-----------------------------------|
| **S0** | Öffentlich | Keine personenbezogenen Daten. Kein Schaden bei Veröffentlichung. | Kein Schaden |
| **S1** | Intern | Betriebsdaten, personenbezogen aber niedriges Risiko. | Geringe Beeinträchtigung |
| **S2** | Vertraulich | Personenbezogene Daten mit finanziellen/vertraglichen Implikationen. | Erheblicher finanzieller Schaden, Regress |
| **S3** | Streng vertraulich / Besondere Kategorien | Art. 9 DSGVO: Gesundheitsdaten, Daten über Mobilitätseinschränkungen, Versicherungsdaten. | Schwere Persönlichkeitsverletzung, hohe Bußgelder (bis 20 Mio. EUR / 4% Umsatz) |

---

## 2. Gesamtübersicht der Datenfelder

### 2.1 Patientendaten (Tabelle: `patients`)

| Feld | Kategorie | S-Stufe | Beispiele | Rechtsgrundlage | Aufbewahrung | Löschfrist |
|------|-----------|---------|-----------|-----------------|-------------|------------|
| `id` | Technische ID | S1 | `42` | Art. 6(1)(f) — berechtigtes Interesse | Betriebsdauer | Mit Patienten-Datensatz |
| `telegram_id` | Pseudonyme ID | S2 | `123456789` | Art. 6(1)(b) — Vertragserfüllung | Betriebsdauer + 3 Jahre (Verjährung) | 3 Jahre nach letzter Fahrt, sofern keine Abrechnung offen |
| `name` | Direkte Personen-ID | S3 | `"Maria Schmidt"` | Art. 6(1)(b) i.V.m. Art. 9(2)(h) | Gesundheitsdienstleistung | 10 Jahre nach letzter Behandlung (§630f BGB analog) |
| `phone` | Kontaktdaten | S2 | `"+49 123 456789"` | Art. 6(1)(b) — Vertragserfüllung | Betriebsdauer + 3 Jahre | 3 Jahre nach letzter Fahrt |
| `default_pickup_addr` | Adresse (Wohnort) | S3 | `"Musterstraße 1, 12345 Berlin"` | Art. 9(2)(h) — Gesundheitsdienstleistung | 10 Jahre (§630f BGB) | 10 Jahre nach letzter Behandlung |
| `default_dest_addr` | Adresse (med. Einrichtung) | S3 | `"Klinikum Nord, Haus C"` | Art. 9(2)(h) — offenbart Behandlungskontext | 10 Jahre (§630f BGB) | 10 Jahre nach letzter Behandlung |
| `insurance_provider` | Krankenkasse | S3 | `"AOK Bayern"` | Art. 9(2)(h) — Gesundheitsdaten | 10 Jahre (§302 SGB V, §147 AO) | 10 Jahre nach letzter Abrechnung |
| `insurance_number` | Versichertennummer | S3 | `"A123456789"` | Art. 9(2)(h) — eindeutiges Gesundheitsmerkmal | 10 Jahre (§302 SGB V) | 10 Jahre nach letzter Abrechnung |
| `vehicle_type` | Fahrzeugtyp (impliziert Mobilität) | S3 | `"Liege"`, `"KTW"`, `"Rollstuhl"` | Art. 9(2)(h) — offenbart Gesundheitszustand | 10 Jahre (§630f BGB) | 10 Jahre nach letzter Behandlung |
| `special_needs` | Besondere Bedürfnisse | S3 | `"Sauerstoffgerät, Rollstuhl"` | Art. 9(2)(h) — explizite Gesundheitsdaten | 10 Jahre (§630f BGB) | 10 Jahre nach letzter Behandlung |
| `notes` | Freitext-Notizen | S3 | `"Patient braucht Hilfe beim Einsteigen"` | Art. 9(2)(h) — kann Gesundheitsdaten enthalten | 10 Jahre (§630f BGB) | 10 Jahre nach letzter Behandlung |
| `created_at` | Metadaten | S1 | `2026-06-06T10:00:00` | Art. 6(1)(f) — Systembetrieb | Mit Datensatz | Mit Patienten-Datensatz |

### 2.2 Fahrerdaten (Tabelle: `drivers`)

| Feld | Kategorie | S-Stufe | Beispiele | Rechtsgrundlage | Aufbewahrung | Löschfrist |
|------|-----------|---------|-----------|-----------------|-------------|------------|
| `id` | Technische ID | S1 | `7` | Art. 6(1)(f) — Systembetrieb | Betriebsdauer | Mit Fahrer-Datensatz |
| `telegram_id` | Pseudonyme ID | S2 | `987654321` | Art. 6(1)(b) — Beschäftigungsverhältnis | Beschäftigungsdauer + 3 Jahre | 3 Jahre nach Beschäftigungsende |
| `name` | Direkte Personen-ID | S2 | `"Thomas Müller"` | Art. 6(1)(b) — Beschäftigungsverhältnis | Beschäftigungsdauer + 3 Jahre | 3 Jahre nach Beschäftigungsende |
| `phone` | Kontaktdaten | S2 | `"+49 176 123456"` | Art. 6(1)(b) — Beschäftigungsverhältnis | Beschäftigungsdauer | Mit Beschäftigungsende, sofern keine Abrechnung offen |
| `p_schein` | Berufsqualifikation | S2 | `true` | Art. 6(1)(b) — Vertragserfüllung, Art. 6(1)(c) — gesetzliche Pflicht (PBefG) | Beschäftigungsdauer + 3 Jahre | 3 Jahre nach Beschäftigungsende |
| `work_hours_start` / `work_hours_end` | Arbeitszeit | S1 | `"07:00"`, `"16:00"` | Art. 6(1)(b) — Beschäftigungsverhältnis | Beschäftigungsdauer | Mit Beschäftigungsende |
| `work_days` | Arbeitstage | S1 | `"Mo,Di,Mi,Do,Fr"` | Art. 6(1)(b) — Beschäftigungsverhältnis | Beschäftigungsdauer | Mit Beschäftigungsende |
| `active` | Beschäftigungsstatus | S1 | `true` | Art. 6(1)(f) — Systembetrieb | Beschäftigungsdauer | Mit Beschäftigungsende |

### 2.3 Fahrtendaten (Tabelle: `trips`)

| Feld | Kategorie | S-Stufe | Beispiele | Rechtsgrundlage | Aufbewahrung | Löschfrist |
|------|-----------|---------|-----------|-----------------|-------------|------------|
| `id` | Technische ID | S1 | `1337` | Art. 6(1)(f) — Systembetrieb | Betriebsdauer | Mit Fahrt-Datensatz |
| `patient_id` (FK) | Verknüpfung Patient | S3 | → Patient | Art. 9(2)(h) — Gesundheitsdienstleistung | 10 Jahre | Mit Patientendaten |
| `driver_id` (FK) | Verknüpfung Fahrer | S2 | → Driver | Art. 6(1)(b) — Vertragserfüllung | 10 Jahre (Abrechnungsbezug) | Mit Abrechnungsdaten |
| `vehicle_id` (FK) | Verknüpfung Fahrzeug | S1 | → Vehicle | Art. 6(1)(f) — Systembetrieb | Betriebsdauer | Mit Fahrt-Datensatz |
| `recurring_template_id` (FK) | Serienfahrt-Vorlage | S1 | → RecurringTrip | Art. 6(1)(f) — Systembetrieb | Betriebsdauer | Mit Fahrt-Datensatz |
| `pickup_addr` | Abholadresse | S3 | `"Seniorenheim Am Park, Zi. 12"` | Art. 9(2)(h) — offenbart Lebensumstände | 10 Jahre (§630f BGB) | 10 Jahre nach letzter Behandlung |
| `dest_addr` | Zieladresse | S3 | `"Dialysezentrum Mitte"` | Art. 9(2)(h) — offenbart Behandlungskontext | 10 Jahre (§630f BGB) | 10 Jahre nach letzter Behandlung |
| `scheduled_pickup` | Geplante Abholzeit | S2 | `2026-06-07T08:00:00` | Art. 6(1)(b) — Vertragserfüllung | 10 Jahre (Abrechnungsbezug) | 10 Jahre nach Abrechnung |
| `scheduled_dropoff` | Geplante Ankunft | S2 | `2026-06-07T08:30:00` | Art. 6(1)(b) — Vertragserfüllung | 10 Jahre (Abrechnungsbezug) | 10 Jahre nach Abrechnung |
| `actual_pickup` | Tatsächliche Abholung | S2 | `2026-06-07T08:12:00` | Art. 6(1)(b) — Vertragserfüllung | 10 Jahre (Abrechnungsbezug) | 10 Jahre nach Abrechnung |
| `actual_dropoff` | Tatsächliche Ankunft | S2 | `2026-06-07T08:45:00` | Art. 6(1)(b) — Vertragserfüllung | 10 Jahre (Abrechnungsbezug) | 10 Jahre nach Abrechnung |
| `status` | Fahrtstatus | S2 | `"abgeschlossen"` | Art. 6(1)(b) — Vertragserfüllung | 10 Jahre | Mit Fahrt-Datensatz |
| `billing_status` | Abrechnungsstatus | S2 | `"exportiert"` | Art. 6(1)(c) — §302 SGB V | 10 Jahre (§147 AO) | 10 Jahre nach Abrechnung (§302 SGB V) |
| `fare_eur` | Fahrpreis | S2 | `35.00` | Art. 6(1)(b) — Vertragserfüllung | 10 Jahre (§147 AO, §257 HGB) | 10 Jahre nach Abrechnung |
| `driver_location_lat` / `driver_location_lon` | Fahrer-GPS (Live-Tracking) | S2 | `52.5200, 13.4050` | Art. 6(1)(b) — Vertragserfüllung | Live — wird nicht persistiert, nur Status-Queries | Keine Speicherung nach Fahrtende |
| `created_at` | Metadaten | S1 | `2026-06-06T10:00:00` | Art. 6(1)(f) — Systembetrieb | Mit Datensatz | Mit Fahrt-Datensatz |

### 2.4 Fahrt-Ereignisse (Tabelle: `trip_events`)

| Feld | Kategorie | S-Stufe | Beispiele | Rechtsgrundlage | Aufbewahrung | Löschfrist |
|------|-----------|---------|-----------|-----------------|-------------|------------|
| `id` | Technische ID | S1 | `5001` | Art. 6(1)(f) — Systembetrieb | Betriebsdauer | Mit Fahrt-Datensatz |
| `trip_id` (FK) | Verknüpfung Fahrt | S2 | → Trip | Art. 6(1)(f) — Audit Trail | 10 Jahre | Mit Fahrt-Datensatz |
| `event_type` | Ereignistyp | S2 | `"status_change"`, `"problem"` | Art. 6(1)(f) — Nachvollziehbarkeit | 10 Jahre | Mit Fahrt-Datensatz |
| `message` | Freitext | S2—S3 | `"Fahrer kam 20 Min zu spät"` | Art. 6(1)(f) — kann personenbezogene Daten enthalten | 10 Jahre (Haftungsrelevanz) | Mit Fahrt-Datensatz. **Warnung: Kann bei Patienten-Löschung pseudonymisiert werden müssen.** |
| `created_at` | Metadaten | S1 | `2026-06-06T10:15:00` | Art. 6(1)(f) — Systembetrieb | Mit Datensatz | Mit Fahrt-Datensatz |

### 2.5 Wiederkehrende Fahrten (Tabelle: `recurring_trips`)

| Feld | Kategorie | S-Stufe | Beispiele | Rechtsgrundlage | Aufbewahrung | Löschfrist |
|------|-----------|---------|-----------|-----------------|-------------|------------|
| `patient_id` (FK) | Verknüpfung Patient | S3 | → Patient | Art. 9(2)(h) | 10 Jahre | Mit Patientendaten |
| `pickup_addr` | Abholadresse | S3 | → siehe Trip | Art. 9(2)(h) | 10 Jahre | Mit Patientendaten |
| `dest_addr` | Zieladresse | S3 | → siehe Trip | Art. 9(2)(h) | 10 Jahre | Mit Patientendaten |
| `cron_days` | Wiederholungstage | S2 | `"Mo,Mi,Fr"` | Art. 6(1)(b) | Betriebsdauer | Mit Serienfahrt |
| `pickup_time` | Abholzeit | S2 | `"07:30"` | Art. 6(1)(b) | Betriebsdauer | Mit Serienfahrt |
| `return_time` | Rückfahrzeit | S2 | `"12:30"` | Art. 6(1)(b) | Betriebsdauer | Mit Serienfahrt |
| `vehicle_type` | Fahrzeugtyp | S3 | `"Liege"` | Art. 9(2)(h) | 10 Jahre | Mit Patientendaten |
| `active_until` | Gültigkeitsende | S1 | `2026-12-31` | Art. 6(1)(f) | Betriebsdauer | Mit Serienfahrt |

### 2.6 Fahrzeuge (Tabelle: `vehicles`)

| Feld | Kategorie | S-Stufe | Beispiele | Rechtsgrundlage | Aufbewahrung | Löschfrist |
|------|-----------|---------|-----------|-----------------|-------------|------------|
| `id` | Technische ID | S1 | `3` | Art. 6(1)(f) | Betriebsdauer | Mit Fahrzeug |
| `license_plate` | Kennzeichen | S2 | `"B-KF 1234"` | Art. 6(1)(f) — Betriebsmittel (auf Fahrer rückführbar) | Betriebsdauer + 3 Jahre | 3 Jahre nach Außerbetriebnahme |
| `vehicle_type` | Fahrzeugtyp | S1 | `"Sitz"` | Art. 6(1)(f) — Betriebsmittel | Betriebsdauer | Mit Fahrzeug |
| `capacity` | Kapazität | S1 | `1` | Art. 6(1)(f) — Betriebsmittel | Betriebsdauer | Mit Fahrzeug |

### 2.7 Fahrerpausen (Tabelle: `driver_breaks`)

| Feld | Kategorie | S-Stufe | Beispiele | Rechtsgrundlage | Aufbewahrung | Löschfrist |
|------|-----------|---------|-----------|-----------------|-------------|------------|
| `driver_id` (FK) | Verknüpfung Fahrer | S2 | → Driver | Art. 6(1)(c) — ArbZG Dokumentation | 2 Jahre (§16 ArbZG) | 2 Jahre nach Kalenderjahr-Ende |
| `start_time` / `end_time` | Pausenzeiten | S2 | `12:00—12:30` | Art. 6(1)(c) — ArbZG | 2 Jahre | 2 Jahre nach Kalenderjahr-Ende |

### 2.8 Verarbeitung außerhalb der Datenbank

| Datenkategorie | Typ | S-Stufe | Beschreibung | Rechtsgrundlage | Aufbewahrung | Löschfrist |
|----------------|-----|---------|-------------|-----------------|-------------|------------|
| **Telegram-Nachrichten (Text)** | Transiente Verarbeitung | S3 | Patient schreibt: "Morgen 8 Uhr zur Dialyse Klinikum Nord" | Art. 9(2)(h) | Telegram-Infrastruktur (Drittland: UAE) | Nach Telegram-Richtlinien; Bot löscht sofort nach Verarbeitung |
| **Telegram-Sprachnachrichten** | Transiente Datei | S3 | Voice Message (.ogg) | Art. 9(2)(h) | Temporär auf Disk (faster-whisper Transkription) | **Sofort nach Transkription löschen** (aktuell: tempfile, `delete=True` im finally-Block → ✓ korrekt implementiert) |
| **DeepSeek API (LLM)** | Drittland-Verarbeitung | S3 | Patientennachricht geht an DeepSeek API (China) zur NLU-Extraktion | Art. 9(2)(h), Art. 49(1)(a) — **ausdrückliche Einwilligung nötig!** | DeepSeek-intern (nicht kontrollierbar) | Nicht kontrollierbar — **Risiko: Daten fließen nach China ohne Angemessenheitsbeschluss** |
| **faster-whisper (lokal)** | Lokale Verarbeitung | S3 | Sprach-zu-Text auf lokalem CPU-Modell | Art. 9(2)(h), Art. 6(1)(f) | Keine Speicherung (flüchtig) | Keine — nur In-Memory-Transkription |
| **Abrechnungs-CSV** | Export-Datei | S3 | `abrechnung_20260606.csv` mit Patientennamen, Versichertennummern, Fahrpreisen | Art. 6(1)(c) — §302 SGB V | 10 Jahre (§147 AO, §257 HGB) | 10 Jahre nach Abrechnung |
| **Muster-4 PDF** | Export-Datei | S3 | `R2026-0042.pdf` mit vollständigen Patientendaten, Versichertennummer, KK-Daten | Art. 6(1)(c) — §302 SGB V | 10 Jahre (§147 AO) | 10 Jahre nach Abrechnung |
| **Logs (structlog)** | Betriebslogs | S1—S3 | JSON-Logs mit `patient_name`, `trip_id` | Art. 6(1)(f) — Systembetrieb | 30 Tage (Betrieb) | 30 Tage — **ACHTUNG: Aktuell KEINE Log-Rotation implementiert!** |
| **Datenbank-Backups** | Sicherung | S1—S3 | `krankenfahrt.db` (SQLite) | Art. 6(1)(c) — Aufbewahrungspflichten | 10 Jahre (enthält Abrechnungsdaten) | 10 Jahre |

---

## 3. Datenflüsse und Verarbeitungsketten

### 3.1 Buchungs-Flow (Sprachnachricht)

```
Patient → Telegram (UAE) → Voice Message (.ogg auf Disk, temp) → faster-whisper (lokal) 
→ Text → DeepSeek API (China) → NLU JSON → BookingIntent → Trip in SQLite
```

**Risiken:**
- **Drittlandtransfer:** Telegram-Server in UAE, DeepSeek-Server in China
- **Kein Angemessenheitsbeschluss** der EU für China (Art. 45 DSGVO)
- **Notwendig:** Art. 49(1)(a) DSGVO — ausdrückliche Einwilligung nach Aufklärung

### 3.2 Buchungs-Flow (Textnachricht)

```
Patient → Telegram (UAE) → Bot Handler → DeepSeek API (China) → NLU JSON → Trip in SQLite
```

### 3.3 Live-Tracking Flow

```
Driver → Telegram → driver_location_lat/lon in Trip → Notification an Patient
```

**Anmerkung:** Aktuell nur als `FloatField` im `Trip`-Modell — wird nur bei Status-Updates gesetzt, kein kontinuierliches Tracking.

### 3.4 Abrechnungs-Flow

```
Chef → /export → Tortoise Query (alle Trips + Patient-Join) → CSV-Datei auf Disk → Telegram File Upload
```

**Risiko:** CSV mit vollen Patientennamen + Versichertennummern wird über Telegram (UAE) übertragen.

### 3.5 Muster-4 Rechnungs-Flow

```
Chef → generate_invoice_for_trips() → Patientendaten + KK-Daten + Fahrten → PDF → Disk
```

---

## 4. Sensitivitätsmatrix nach Datenkategorie

| Datenkategorie | S0 | S1 | S2 | S3 | DSGVO-Artikel |
|----------------|----|----|----|-----|---------------|
| Technische IDs (autoincrement) | | ✓ | | | Art. 6(1)(f) |
| Pseudonyme IDs (telegram_id) | | | ✓ | | Art. 6(1)(b) |
| Name Patient | | | | ✓ | Art. 9(2)(h) |
| Name Fahrer | | | ✓ | | Art. 6(1)(b) |
| Adresse (Wohnort) | | | | ✓ | Art. 9(2)(h) |
| Adresse (med. Einrichtung) | | | | ✓ | Art. 9(2)(h) |
| Telefonnummer | | | ✓ | | Art. 6(1)(b) |
| Krankenkasse | | | | ✓ | Art. 9(2)(h) |
| Versichertennummer | | | | ✓ | Art. 9(2)(h) |
| Fahrzeugtyp (impliziert Mobilität) | | | | ✓ | Art. 9(2)(h) |
| Special Needs (Gesundheitsdaten) | | | | ✓ | Art. 9(2)(h) |
| Fahrtziele (Behandlungskontext) | | | | ✓ | Art. 9(2)(h) |
| Fahrpreise | | | ✓ | | Art. 6(1)(b) |
| Fahrer-GPS (Live) | | | ✓ | | Art. 6(1)(b) |
| Fahrer-Qualifikationen | | | ✓ | | Art. 6(1)(c) |
| Fahrer-Arbeitszeiten | | ✓ | | | Art. 6(1)(c) |
| Fahrzeug-Kennzeichen | | | ✓ | | Art. 6(1)(f) |
| Fahrzeug-Typ/Kapazität | | ✓ | | | Art. 6(1)(f) |
| Audit-Logs (TripEvents) | | | ✓¹ | | Art. 6(1)(f) |
| Sprachaufnahmen (.ogg) | | | | ✓ | Art. 9(2)(h) |
| LLM-Prompts (an DeepSeek) | | | | ✓ | Art. 9(2)(h), Art. 49(1)(a) |
| Muster-4 PDF | | | | ✓ | Art. 6(1)(c) |
| Abrechnungs-CSV | | | | ✓ | Art. 6(1)(c) |

¹ TripEvents mit `message`-Feld können S3-Daten enthalten, wenn sie Patientengesundheitsdaten referenzieren.

---

## 5. Aufbewahrungsfristen — Zusammenfassung

| Kategorie | Frist | Rechtsgrundlage | Beginn der Frist |
|-----------|-------|-----------------|------------------|
| **Patientendaten (klinisch)** | 10 Jahre | §630f Abs. 3 BGB (analog) | Ende des Kalenderjahres der letzten Behandlung/Fahrt |
| **Abrechnungsdaten (§302 SGB V)** | 10 Jahre | §302 SGB V, §304 SGB V | Ende des Kalenderjahres der Abrechnung |
| **Steuerrelevante Daten** | 10 Jahre | §147 AO, §257 HGB | Ende des Kalenderjahres der Entstehung |
| **Fahrerdaten (Beschäftigung)** | 3 Jahre | §195 BGB (Regelverjährung) | Ende der Beschäftigung |
| **Fahrer-Arbeitszeitdokumentation** | 2 Jahre | §16 Abs. 2 ArbZG | Ende des Kalenderjahres |
| **Telegram-Nachrichten** | Keine Speicherung | Art. 5(1)(c) DSGVO (Datenminimierung) | Bot verarbeitet und verwirft |
| **Sprachaufnahmen (temp)** | Sofort nach Transkription | Art. 5(1)(c) DSGVO | Nach NLU-Extraktion |
| **System-Logs** | 30 Tage (Maximum) | Art. 5(1)(e) DSGVO | Rollierend |
| **Einwilligungen** | Dauer der Verarbeitung + 3 Jahre | Art. 7(1) DSGVO, §195 BGB | Ab Widerruf / letzter Verarbeitung |
| **Datenbank (Gesamt)** | Maximum der enthaltenen Fristen (10 Jahre) | Kumulativ | Siehe längste Einzelfrist |

---

## 6. Kritische Findings & Compliance-Lücken

### 6.1 SCHWERWIEGEND — Drittlandtransfer ohne Rechtsgrundlage

**Betrifft:** DeepSeek API (China), Telegram (UAE)

Beide Länder haben **keinen Angemessenheitsbeschluss** der EU-Kommission nach Art. 45 DSGVO.
Die Übermittlung von S3-Gesundheitsdaten an diese Drittländer erfordert:

1. **Art. 49(1)(a) DSGVO:** Ausdrückliche, informierte Einwilligung des Patienten NACH Aufklärung über:
   - Dass Daten nach China (DeepSeek) und UAE (Telegram) übermittelt werden
   - Dass kein Angemessenheitsbeschluss besteht
   - Dass keine geeigneten Garantien nach Art. 46 DSGVO bestehen
   - Welche konkreten Daten übermittelt werden (Gesundheitsdaten!)

2. **Alternativ:** Vorab von DeepSeek ein Data Processing Agreement (DPA/AVV) mit Standardvertragsklauseln (SCC) nach Art. 46(2)(c) DSGVO einholen.

3. **Oder:** Migration auf EU-gehostetes LLM (z.B. Aleph Alpha, Mistral EU, lokales Modell via Ollama).

### 6.2 SCHWERWIEGEND — Keine Trennung von klinischen und Abrechnungsdaten

Patienten müssen nach DSGVO Art. 17 ein Recht auf Löschung haben. Allerdings müssen
Abrechnungsdaten 10 Jahre aufbewahrt werden (§302 SGB V, §147 AO).

**Aktueller Zustand:** Alle Daten in einer SQLite-Datenbank ohne Trennung.

**Lösung:**
- `Patient`-Tabelle in zwei Teile splitten: `PatientClinical` (löschbar) und `PatientBilling` (10 Jahre)
- ODER: Bei Löschung: Name/Adresse pseudonymisieren, aber Abrechnungs-ID + Versichertennummer behalten
- **Implementiert?** NEIN. Siehe REQUIREMENTS_EDGE_CASES.md UC-14.

### 6.3 MITTEL — Keine Einwilligungsverwaltung

Es fehlen:
- `Patient.consent_given_at` (Timestamp der Einwilligung)
- `Patient.consent_version` (welche Version der Datenschutzerklärung)
- `Patient.consent_withdrawn_at` (Widerruf)
- `Patient.data_retention_until` / `Patient.deletion_requested_at`

### 6.4 MITTEL — Keine Log-Daten-Rotation

structlog schreibt JSON-Logs, die potenziell Patientennamen und Fahrtdetails enthalten.
Es gibt keine Log-Rotation, keine Retention Policy. Aktuell unbegrenztes Wachstum mit
personenbezogenen Daten in Logs.

### 6.5 MITTEL — Fahrer-GPS-Daten unklar

`driver_location_lat/lon` werden im Trip-Modell gespeichert, aber:
- Unklar ob sie nach Fahrtende erhalten bleiben (sollten sie nicht)
- Keine Dokumentation wann/wie sie gelöscht werden
- Bei Taxi-/Krankentransport-Diensten: GPS-Tracking kann unter DSGVO fallen, wenn es Bewegungsprofile erstellt

### 6.6 NIEDRIG — Telegram ID als personenbezogenes Datum

Die Telegram User ID ist ein personenbezogenes Datum (eindeutig, nicht änderbar).
Sie wird in der DB gespeichert. DSGVO-konform, aber bei Auskunftsersuchen (Art. 15)
muss sie mit ausgegeben werden.

### 6.7 NIEDRIG — TripEvent.message als unkontrollierter Freitext

Das `message`-Feld in `TripEvent` kann beliebige personenbezogene Daten enthalten.
Es gibt keine Validierung oder Filterung. Bei einem Auskunftsersuchen sind alle
Events mit Patientenbezug offenzulegen.

---

## 7. Empfohlene Sofortmaßnahmen (Priorität)

| # | Maßnahme | Prio | Aufwand | Risiko-Reduktion |
|---|----------|------|---------|-----------------|
| 1 | **Einwilligungs-Management implementieren** (`consent_given_at`, `consent_version`, Datenfelder hinzufügen) | P1 | 2h | Ermöglicht überhaupt erst rechtskonforme Verarbeitung |
| 2 | **Datenschutzerklärung verfassen** und im Bot-Onboarding einholen (mit explizitem Hinweis auf DeepSeek/China und Telegram/UAE) | P1 | 4h | Rechtliche Grundvoraussetzung |
| 3 | **Datenfelder für Löschung/Pseudonymisierung** (`data_retention_until`, `deletion_requested_at`) | P1 | 1h | Art. 17 DSGVO Compliance |
| 4 | **LLM-Migration evaluieren** (DeepSeek China → EU-Alternative oder lokales Modell) | P2 | 8h | Eliminiert größtes Drittland-Risiko |
| 5 | **Log-Rotation mit Retention Policy** einrichten (max. 30 Tage, keine S3-Daten auf INFO-Level) | P2 | 2h | Betriebssicherheit + DSGVO |
| 6 | **Abrechnungsdaten von klinischen Daten trennen** (separate Tabelle oder Pseudonymisierung) | P2 | 6h | Ermöglicht Löschung nach Art. 17 |
| 7 | **AVV mit DeepSeek abschließen** (wenn LLM-Migration nicht möglich) | P2 | Abhängig von DeepSeek | Reduziert Drittland-Risiko |
| 8 | **TripEvent.message-Filter** — keine Gesundheitsdaten in Freitext speichern | P3 | 2h | Datenminimierung |

---

## 8. Rechtsgrundlagen-Verzeichnis

| Rechtsgrundlage | Anwendung im System |
|----------------|---------------------|
| **Art. 6(1)(a) DSGVO** | Einwilligung (muss noch implementiert werden — siehe §6.3) |
| **Art. 6(1)(b) DSGVO** | Vertragserfüllung: Transportbuchung, Fahrerzuweisung, Abrechnung |
| **Art. 6(1)(c) DSGVO** | Rechtliche Verpflichtung: §302 SGB V Abrechnung, ArbZG Pausen, PBefG |
| **Art. 6(1)(f) DSGVO** | Berechtigtes Interesse: Systembetrieb, Audit Trail, technische IDs |
| **Art. 9(2)(h) DSGVO** | Gesundheitsdaten für Gesundheitsdienstleistung (Krankentransport) |
| **Art. 9(2)(f) DSGVO** | Rechtsansprüche (Haftung, Abrechnungsstreitigkeiten) |
| **Art. 49(1)(a) DSGVO** | Ausnahme Drittlandtransfer: **ausdrückliche Einwilligung nötig** (DeepSeek, Telegram) |
| **§22 BDSG** | Nationale Öffnungsklausel für Art. 9 DSGVO |
| **§630f BGB** | Dokumentationspflicht Patientenakte (10 Jahre) — analog für Transportsystem anwendbar |
| **§302 SGB V** | Abrechnung Krankentransport mit GKV (Muster-4) |
| **§304 SGB V** | Aufbewahrung Abrechnungsdaten (10 Jahre) |
| **§147 AO** | Steuerliche Aufbewahrungsfrist (10 Jahre) |
| **§257 HGB** | Handelsrechtliche Aufbewahrungsfrist (10 Jahre) |
| **§16 ArbZG** | Arbeitszeitdokumentation (2 Jahre) |

---

## 9. Datenlöschung / Pseudonymisierung — Konzept

### 9.1 Patient fordert Löschung (Art. 17 DSGVO)

1. **Prüfen:** Sind noch Abrechnungsdaten vorhanden, die <10 Jahre alt sind?
2. **Wenn NEIN:** Komplette Löschung des Patienten-Datensatzes und aller verknüpften Trips.
3. **Wenn JA:** Klinische Daten löschen, Abrechnungsdaten pseudonymisieren:
   - `name` → `"GELÖSCHT-{UUID}"`
   - `phone` → `NULL`
   - `telegram_id` → `NULL` (wichtig: Patient kann Bot nicht mehr nutzen!)
   - `default_pickup_addr` → `"GELÖSCHT"`
   - `default_dest_addr` → `"GELÖSCHT"`
   - `special_needs` → `NULL`
   - `notes` → `NULL`
   - `insurance_provider` + `insurance_number` → Behalten (für Abrechnungsnachweis)
   - Trip-Daten: `pickup_addr`, `dest_addr` → `"GELÖSCHT"`. `driver_location_*` → `NULL`.

### 9.2 Automatische Löschfristen

- **Cron-Job täglich:** Prüft `data_retention_until` — wenn erreicht + keine offene Abrechnung → löschen/pseudonymisieren
- **Logs:** Wöchentlicher Cron-Job löscht Logs älter als 30 Tage

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
| **Art. 45 DSGVO** | Angemessenheitsbeschluss (Drittlandtransfer) |
| **Art. 49 DSGVO** | Ausnahmen für Drittlandtransfer |
| **AVV** | Auftragsverarbeitungsvertrag (Data Processing Agreement) |
| **SCC** | Standardvertragsklauseln (Standard Contractual Clauses) |
| **Muster-4** | Abrechnungsformular für Krankentransport nach §302 SGB V |
| **IK-Nummer** | Institutionskennzeichen der Krankenkassen |
| **PHI** | Protected Health Information (HIPAA-Äquivalent, hier nicht direkt anwendbar) |

---

*Dokument erstellt am 06.06.2026 durch automatisierte Datenklassifikation.*
*Zuletzt geprüft: 06.06.2026*
*Nächste Überprüfung: 06.12.2026 (6-Monats-Rhythmus)*
