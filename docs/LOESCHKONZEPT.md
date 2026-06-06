# Löschkonzept — Moradbakhti-KI (Krankenfahrt)

**Zweck:** Systematisches Löschkonzept gemäß Art. 17 DSGVO und DIN 66398 (jetzt DIN EN
ISO/IEC 27555:2025-09) für alle personenbezogenen Daten, die durch das
Krankenfahrt-System verarbeitet werden. Definiert automatisierte Löschregeln, manuelle
Prüftrigger, Löschklassen und Nachweisverfahren.

**Stand:** 06.06.2026
**Verantwortlicher:** Moradbakhti-KI (siehe Impressum in `config.py`)
**System:** Krankenfahrt — AI-First Medical Transport Dispatch (v0.3.0)
**Grundlage:** DATENKLASSIFIKATION.md v1.0, AVV_Auftragsverarbeitungsvertrag_Muster.md
**Nächste Überprüfung:** 06.12.2026 (6-Monats-Rhythmus)

---

## 1. Rechtliche Grundlagen des Löschkonzepts

### 1.1 Pflicht zum Löschkonzept

Die Pflicht zur Einrichtung eines Löschkonzepts ergibt sich aus mehreren DSGVO-Vorschriften:

| Norm | Inhalt | Konsequenz für Krankenfahrt |
|------|--------|----------------------------|
| **Art. 5 Abs. 1 lit. e DSGVO** | Speicherbegrenzung: Daten nur so lange in identifizierbarer Form, wie für die Zwecke erforderlich | Muss Löschfristen pro Datenkategorie definieren und technisch durchsetzen |
| **Art. 5 Abs. 2 DSGVO** | Rechenschaftspflicht: Nachweis der Einhaltung | Muss Löschungen protokollieren und dokumentieren |
| **Art. 17 DSGVO** | Recht auf Löschung („Recht auf Vergessenwerden\") | Muss Patientenanträge auf Löschung innerhalb 1 Monat bearbeiten |
| **Art. 19 DSGVO** | Mitteilungspflicht bei Löschung | Muss alle Empfänger der Daten über Löschung informieren |
| **Art. 30 Abs. 1 lit. f DSGVO** | Dokumentation im VVT: Löschfristen je Datenkategorie | Im Verarbeitungsverzeichnis zu dokumentieren |
| **Art. 32 DSGVO** | Sicherheit der Verarbeitung inkl. Löschung | Technische Maßnahmen für irreversible Löschung |

### 1.2 Einschlägige Ausnahmen von der Löschpflicht (Art. 17 Abs. 3 DSGVO)

Nicht gelöscht werden **muss**, soweit die Verarbeitung erforderlich ist:

| Ausnahme | Anwendung im System |
|----------|-------------------|
| **lit. b: Rechtliche Verpflichtung** | §302 SGB V (10 Jahre Abrechnungsdaten), §147 AO (10 Jahre Steuerdaten), §257 HGB (10 Jahre Handelsbücher), §16 ArbZG (2 Jahre Arbeitszeit) |
| **lit. d: Archivzwecke** | Forschungs- und Statistikzwecke nach Art. 89 DSGVO (optional, mit Pseudonymisierung) |
| **lit. e: Rechtsansprüche** | Datenaufbewahrung für Haftungsansprüche (§§195, 199 BGB: 3 Jahre Regelverjährung, 30 Jahre bei Personenschäden) |

### 1.3 SGB X §84 — Besonderheiten für Sozialdaten

Da das System faktisch Gesundheitsdaten i.S.d. §67 SGB X verarbeitet (Krankentransport mit
GKV-Abrechnung), gelten ergänzend:

- **§84 Abs. 1 SGB X:** Bei nicht automatisierter Verarbeitung, wenn Löschung
  unverhältnismäßig aufwendig: Einschränkung der Verarbeitung (Sperrung) statt Löschung
- **§84 Abs. 4 SGB X:** Bei satzungsmäßigen/vertraglichen Aufbewahrungsfristen:
  Einschränkung der Verarbeitung statt Löschung

> **Für Krankenfahrt relevant:** Da 100% automatisierte Verarbeitung in SQLite — §84 Abs. 1
> greift nicht. Aber §84 Abs. 4 ist relevant: Abrechnungsdaten mit 10-Jahres-Frist nach
> §302 SGB V fallen unter die Löschausnahme.

---

## 2. Löschklassen nach DIN 66398

### 2.1 Definition der Löschklassen

Jede Löschklasse gruppiert Datenkategorien mit identischem Löschtrigger und identischer
Löschfrist. Die Kodierung folgt dem Schema:

```
LK-{Sensitivitätsstufe}{Frist}{Trigger}
  Trigger: EV = Ereignisbezogen, ZT = Zeitablauf, AR = Auf unbestimmte Zeit (Abruf nötig)
```

Beispiel: `LK-S3-10Y-EV` = S3-Daten, 10 Jahre nach Ereignis löschen.

### 2.2 Löschklassen-Übersicht

| ID | Sensitivität | Frist | Trigger | Beschreibung | Betroffene Daten |
|----|-------------|-------|---------|-------------|-----------------|
| **LK-S3-10Y-EV** | S3 | 10 Jahre | Ende des Kalenderjahres der letzten Behandlung/Fahrt | Patientendaten (klinisch) | `patients`: name, default_pickup_addr, default_dest_addr, vehicle_type, special_needs, notes; `trips`: pickup_addr, dest_addr; `recurring_trips`: pickup_addr, dest_addr, vehicle_type |
| **LK-S3-10Y-BIL** | S3 | 10 Jahre | Ende des Kalenderjahres der Abrechnung | Abrechnungsbezogene Patientendaten | `patients`: insurance_provider, insurance_number; `trips`: fare_eur, billing_status; Muster-4 PDF; Abrechnungs-CSV |
| **LK-S2-3Y-CON** | S2 | 3 Jahre | Ende des Kalenderjahres nach Vertragsende | Vertragsbezogene Kommunikationsdaten | `patients`: telegram_id, phone; `drivers`: telegram_id, name, phone, p_schein; `trips`: driver_id |
| **LK-S2-10Y-FIN** | S2 | 10 Jahre | Ende des Kalenderjahres der Entstehung | Steuer- und handelsrechtlich relevante Fahrtendaten | `trips`: scheduled_pickup, scheduled_dropoff, actual_pickup, actual_dropoff, status, fare_eur |
| **LK-S2-2Y-AZG** | S2 | 2 Jahre | Ende des Kalenderjahres | Arbeitszeitdokumentation | `driver_breaks`: start_time, end_time, driver_id |
| **LK-S2-0D-LIVE** | S2 | 0 Tage (sofort) | Fahrtende | Live-GPS-Daten — sofortige Löschung | `trips`: driver_location_lat, driver_location_lon |
| **LK-S1-SYS** | S1 | Betriebsdauer | Systemende / Datensatz-Lebenszyklus | Technische IDs und Systemdaten | `id`-Felder aller Tabellen, `created_at`, `vehicle_id` FK, `recurring_template_id` FK, work_hours, work_days, active-Status |
| **LK-S3-0D-TEMP** | S3 | 0 Tage (sofort) | Nach Transkription | Temporäre Sprachaufnahmen | Voice Message (.ogg) auf Disk |
| **LK-S3-0D-LLM** | S3 | 0 Tage | Nicht kontrollierbar (Drittland) | LLM-Prompts an DeepSeek | Patientennachrichten an DeepSeek API |
| **LK-S1-30D-LOG** | S1—S3 | 30 Tage | Rollierend (Datum der Log-Zeile) | System-Logs | structlog JSON-Logs |
| **LK-S2-3Y-CONSENT** | S2 | 3 Jahre | Ab Widerruf / letzter Verarbeitung | Einwilligungsdokumentation | `consent_given_at`, `consent_version`, `consent_withdrawn_at` |
| **LK-S3-10Y-BACKUP** | S1—S3 | 10 Jahre | Siehe längste Einzelfrist | Datenbank-Backups | `krankenfahrt.db` |
| **LK-S3-10Y-EXPORT** | S3 | 10 Jahre | Ende des Kalenderjahres der Erstellung | Export-Dateien | CSV-Dateien, PDF-Dateien (Muster-4) auf Disk |
| **LK-TRANSIENT** | S3 | Keine Speicherung | Kein Trigger (flüchtig) | Transiente Telegram-Verarbeitung | Telegram-Nachrichten-Text (Bot verarbeitet und verwirft) |

### 2.3 Löschklassen-Matrix (DIN 66398 konform)

| Löschklasse | Start-Trigger | Dauer | Gesetzliche Grundlage | Automatisierbar? |
|------------|---------------|-------|----------------------|-----------------|
| LK-S3-10Y-EV | `MAX(Patient.last_trip_date, Patient.created_at)` → 31.12. des Jahres | 10 Jahre | §630f Abs. 3 BGB (analog) | Ja (Cron-Prüfung, dann Deletion-Skript) |
| LK-S3-10Y-BIL | Letztes Abrechnungsdatum → 31.12. des Jahres | 10 Jahre | §302 SGB V, §304 SGB V, §147 AO | Ja (nach Ablauf, sofern keine offenen Abrechnungen) |
| LK-S2-3Y-CON | Ende Beschäftigungsverhältnis / letzte Fahrt → 31.12. des Jahres | 3 Jahre | §195 BGB (Regelverjährung) | Ja |
| LK-S2-10Y-FIN | Fahrtdatum → 31.12. des Jahres | 10 Jahre | §147 AO, §257 HGB | Ja |
| LK-S2-2Y-AZG | Pausendatum → 31.12. des Jahres | 2 Jahre | §16 Abs. 2 ArbZG | Ja |
| LK-S2-0D-LIVE | `trip.actual_dropoff IS NOT NULL` | 0 Tage | Art. 5(1)(c) DSGVO | Ja (direkt bei Fahrtende-Setzung) |
| LK-S1-SYS | Ende des Systemlebenszyklus | — | Art. 6(1)(f) DSGVO | Nein (Betriebsdauer) |
| LK-S3-0D-TEMP | `finally`-Block nach Transkription | 0 Tage | Art. 5(1)(c) DSGVO | Ja (bereits implementiert ✓) |
| LK-S3-0D-LLM | Nach API-Call | 0 Tage (nicht kontrollierbar) | Art. 49(1)(a) DSGVO | Nein — Drittland-Risiko; Migration nötig |
| LK-S1-30D-LOG | `log.timestamp` | 30 Tage | Art. 5(1)(e) DSGVO | Ja (Cron: tägliche Log-Rotation) |
| LK-S2-3Y-CONSENT | `consent_withdrawn_at OR last_processing` → 31.12. des Jahres | 3 Jahre | Art. 7(1) DSGVO, §195 BGB | Ja |
| LK-S3-10Y-BACKUP | Erstellungsdatum des Backups → 31.12. des Jahres | 10 Jahre | Kumulativ (max. Einzelfrist) | Ja |
| LK-S3-10Y-EXPORT | Erstellungsdatum → 31.12. des Jahres | 10 Jahre | §147 AO, §302 SGB V | Ja |
| LK-TRANSIENT | — | — | Art. 5(1)(c) DSGVO | N/A (keine Speicherung) |

---

## 3. Automatisierte Löschregeln

### 3.1 Regelwerk — Cron-Job „Löschung täglich\"

**Ausführung:** Täglich um 03:00 UTC
**Datei:** `scripts/deletion_cron.py`
**Funktionsweise:**

```
FOR EACH Löschklasse:
  1. Berechne Löschtermin: Start-Trigger + Frist
  2. Query: SELECT * WHERE löschtermin <= NOW()
  3. Für LK-S3-10Y-BIL: Zusätzlich prüfen ob billing_status = 'abgeschlossen'
  4. Für Datensätze mit S3: Führe gestufte Löschung aus (siehe §5)
  5. Für Datensätze S1/S2: Direkte DELETION
  6. Schreibe Löschprotokoll-Eintrag (siehe §7)
  7. Bei Fehler: Schreibe in `deletion_errors`-Tabelle + Alarmierung
```

### 3.2 Einzelregeln pro Löschklasse

#### REGEL-01: Patientendaten (klinisch) — `LK-S3-10Y-EV`

```sql
-- Prüfung auf Löschreife
SELECT p.id, p.name, p.created_at,
       (SELECT MAX(t.scheduled_pickup) FROM trips t WHERE t.patient_id = p.id) AS last_trip,
       (SELECT MAX(te.created_at) FROM trip_events te
        JOIN trips t2 ON te.trip_id = t2.id
        WHERE t2.patient_id = p.id) AS last_event
FROM patients p
WHERE p.deletion_requested_at IS NOT NULL  -- Patient hat Löschung beantragt
  AND (SELECT COUNT(*) FROM trips t3
       WHERE t3.patient_id = p.id
         AND t3.billing_status != 'abgeschlossen'
         AND t3.fare_eur > 0) = 0           -- Keine offenen Abrechnungen
  AND DATE(
    COALESCE(
      (SELECT MAX(t4.scheduled_pickup) FROM trips t4 WHERE t4.patient_id = p.id),
      p.created_at
    ),
    '+10 years', 'start of year', '+1 year'
  ) <= DATE('now');                         -- 10 Jahre nach letzter Fahrt
```

**Aktion:** Gestufte Löschung nach §5.1

**Automatisiert:** JA

**Ausnahme-Treatment:** Wenn 10-Jahres-Frist noch nicht abgelaufen, aber Patient Löschung
fordert → Pseudonymisierung nach §5.1.

---

#### REGEL-02: Abrechnungsdaten — `LK-S3-10Y-BIL`

```sql
SELECT t.id, t.patient_id, t.fare_eur, t.billing_status
FROM trips t
LEFT JOIN patients p ON t.patient_id = p.id
WHERE t.billing_status = 'abgeschlossen'
  AND DATE(t.scheduled_pickup, '+10 years', 'start of year', '+1 year') <= DATE('now');
```

**Aktion:** Löschung von `fare_eur`, `billing_status`, `insurance_provider`, `insurance_number`
aus Patient. Bei Trips: Nur abrechnungsbezogene Felder löschen
(`fare_eur`, `billing_status`). Restliche Trip-Daten bleiben für klinische
Dokumentation (LK-S3-10Y-EV).

**Automatisiert:** JA

**Besonderheit:** Wenn ein Patient innerhalb von 10 Jahren gelöscht wurde, aber
Abrechnungsdaten noch nicht abgelaufen sind → Abrechnungsdaten pseudonymisiert behalten
(siehe §5.1).

---

#### REGEL-03: Vertragsdaten (Patient/Fahrer) — `LK-S2-3Y-CON`

```sql
-- Patienten-Kontaktdaten
UPDATE patients
SET telegram_id = NULL, phone = NULL
WHERE DATE(COALESCE(
  (SELECT MAX(t.scheduled_pickup) FROM trips t WHERE t.patient_id = patients.id),
  patients.created_at
), '+3 years', 'start of year', '+1 year') <= DATE('now')
  AND (SELECT COUNT(*) FROM trips t2
       WHERE t2.patient_id = patients.id
         AND t2.billing_status != 'abgeschlossen') = 0;

-- Fahrerdaten
DELETE FROM drivers
WHERE DATE(COALESCE(ended_at, created_at), '+3 years', 'start of year', '+1 year') <= DATE('now')
  AND active = FALSE;
```

**Automatisiert:** JA

**Achtung Fahrer:** `drivers.active=FALSE` muss gesetzt sein. Keine offenen
Abrechnungszuordnungen. `ended_at` Feld muss existieren (ggf. hinzufügen).

---

#### REGEL-04: Steuer-/Handelsdaten — `LK-S2-10Y-FIN`

```sql
-- Reine Fahrtendaten ohne Personenbezug
UPDATE trips
SET fare_eur = NULL,
    billing_status = 'gelöscht'
WHERE DATE(scheduled_pickup, '+10 years', 'start of year', '+1 year') <= DATE('now')
  AND billing_status = 'abgeschlossen';
```

**Aktion:** Finanzdaten werden genullt, aber Trip-Struktur bleibt für klinischen Kontext.

**Automatisiert:** JA

---

#### REGEL-05: Arbeitszeitdokumentation — `LK-S2-2Y-AZG`

```sql
DELETE FROM driver_breaks
WHERE DATE(COALESCE(end_time, start_time), '+2 years', 'start of year', '+1 year') <= DATE('now');
```

**Automatisiert:** JA

---

#### REGEL-06: Live-GPS-Daten — `LK-S2-0D-LIVE`

```sql
-- Ausführung SOFORT bei Fahrtende (trigger_by_trip_completion)
UPDATE trips
SET driver_location_lat = NULL, driver_location_lon = NULL
WHERE actual_dropoff IS NOT NULL
  AND (driver_location_lat IS NOT NULL OR driver_location_lon IS NOT NULL);
```

**Automatisiert:** JA — muss im Code-Pfad `complete_trip()` unmittelbar ausgeführt werden.

**Implementierungsstatus:** ❌ NOCH NICHT IMPLEMENTIERT — aktuell werden GPS-Daten nicht
explizit genullt bei Fahrtende. MUSS vor Produktivbetrieb implementiert werden.

---

#### REGEL-07: Sprachaufnahmen (temp) — `LK-S3-0D-TEMP`

```python
# Bereits korrekt implementiert in voice processing pipeline
try:
    result = transcribe(tempfile_path)
finally:
    if os.path.exists(tempfile_path):
        os.remove(tempfile_path)  # delete=True im Kontextmanager
```

**Automatisiert:** JA ✓ (bereits implementiert)

**Verifikation:** In `VoiceProcessor.process_voice_message()` prüfen, dass `delete=True`
gesetzt und im `finally`-Block sichergestellt.

---

#### REGEL-08: System-Logs — `LK-S1-30D-LOG`

```python
# logrotate oder Cron-Job
import os, time
LOG_DIR = "logs/"
MAX_AGE_DAYS = 30
cutoff = time.time() - (MAX_AGE_DAYS * 86400)
for f in os.listdir(LOG_DIR):
    fp = os.path.join(LOG_DIR, f)
    if os.path.isfile(fp) and os.path.getmtime(fp) < cutoff:
        os.remove(fp)
        log_deletion("log", fp, "Alter > 30 Tage")
```

**Automatisiert:** JA (Cron-Job)

**Implementierungsstatus:** ❌ NOCH NICHT IMPLEMENTIERT — aktuell keine Log-Rotation.

**Dringlichkeit:** P1 — Logs enthalten potenziell Patientennamen (S3).

---

#### REGEL-09: Einwilligungsdokumentation — `LK-S2-3Y-CONSENT`

```sql
-- Löschung der Einwilligungs-Metadaten, nicht der Einwilligung selbst
UPDATE patients
SET consent_given_at = NULL, consent_version = NULL
WHERE consent_withdrawn_at IS NOT NULL
  AND DATE(consent_withdrawn_at, '+3 years', 'start of year', '+1 year') <= DATE('now');
```

**Aktion:** Einwilligungsmetadaten löschen, 3 Jahre nach Widerruf. Die dokumentierte
Einwilligung selbst (in `consent_records` Tabelle) wird für Nachweiszwecke pseudonymisiert
archiviert.

**Automatisiert:** JA

**Implementierungsstatus:** ❌ Felder `consent_given_at`, `consent_version`,
`consent_withdrawn_at` existieren noch nicht im Datenmodell.

---

#### REGEL-10: Datenbank-Backups — `LK-S3-10Y-BACKUP`

```python
# Cron-Job: wöchentlich (Sonntag 02:00 UTC)
for backup_file in glob("backups/krankenfahrt_*.db"):
    file_date = extract_date_from_filename(backup_file)
    if file_date + timedelta(days=3650) <= now():
        secure_delete(backup_file)  # Überschreiben + Löschen
        log_deletion("backup", backup_file, "10-Jahres-Frist abgelaufen")
```

**Automatisiert:** JA

**Implementierungsstatus:** ❌ Noch keine Backup-Rotation implementiert.

---

#### REGEL-11: Export-Dateien (CSV/PDF) — `LK-S3-10Y-EXPORT`

```python
# Cron-Job: wöchentlich (Montag 04:00 UTC)
EXPORT_DIRS = ["exports/csv/", "exports/pdf/"]
for d in EXPORT_DIRS:
    for f in os.listdir(d):
        fp = os.path.join(d, f)
        file_date = get_creation_date(fp)
        if file_date + timedelta(days=3650) <= now():
            secure_delete(fp)
            log_deletion("export", fp, "10-Jahres-Frist abgelaufen")
```

**Automatisiert:** JA

**Besonderheit:** Abrechnungs-CSVs und Muster-4-PDFs werden auf Disk gespeichert. Diese
Dateien sind S3-Daten und müssen nach Ablauf der 10-Jahres-Frist **unwiderruflich**
gelöscht werden.

---

### 3.3 Sonderregel: Telegram-Nachrichten

Telegram-Nachrichten (Text) werden vom Bot verarbeitet, aber **nicht in der Datenbank
gespeichert**. Der Bot extrahiert die relevanten Daten (Name, Adresse, Zeit, Ziel) und
erstellt einen Trip-Datensatz. Die ursprüngliche Nachricht wird **verworfen**.

- **Speicherort:** Telegram-Server (UAE — Drittland, nicht DSGVO-konform)
- **Kontrolle:** Keine — liegt außerhalb des Einflussbereichs von Moradbakhti-KI
- **Löschung:** Nach Telegram-Richtlinien (max. 24h für Bot-Nachrichten lt. Telegram API
  Retention, aber nicht garantierbar)
- **Risiko:** ⚠️ Drittlandtransfer ohne Angemessenheitsbeschluss — siehe Finding 6.1
  in DATENKLASSIFIKATION.md
- **Empfohlen:** Migration auf EU-Messaging (Matrix/Element mit E2EE) oder zumindest
  informierte Einwilligung nach Art. 49(1)(a) DSGVO einholen

---

## 4. Manuelle Prüftrigger

### 4.1 Patient fordert Löschung (Art. 17 DSGVO)

**Auslöser:** Patient stellt Löschantrag (per Chat, Telefon, E-Mail, Brief)

**Prozess:**

```
SCHRITT 1 — IDENTIFIZIERUNG (innerhalb 48h)
  ├─ Prüfung der Identität des Antragstellers
  │   ├─ Bei Telegram: telegram_id + Verifikationsfrage (Name, letzte Fahrt)
  │   └─ Bei schriftlichem Antrag: Kopie Ausweis (geschwärzt außer Name/Geburtsdatum)
  └─ Dokumentation: Antragseingang, Identifikationsmethode, Timestamp

SCHRITT 2 — PRÜFUNG (innerhalb 7 Tage)
  ├─ Datenbank-Query: Existieren Daten zum Antragsteller?
  ├─ Prüfung offener Abrechnungen:
  │   SELECT COUNT(*) FROM trips
  │   WHERE patient_id = ? AND billing_status != 'abgeschlossen' AND fare_eur > 0
  ├─ Prüfung gesetzlicher Aufbewahrungsfristen:
  │   ├─ Abrechnungsdaten < 10 Jahre? → Pseudonymisierung nötig
  │   ├─ Klinische Daten < 10 Jahre? → Pseudonymisierung nötig (wenn Abrechnung offen)
  │   └─ Keine Fristen aktiv? → Volllöschung möglich

SCHRITT 3 — AUSFÜHRUNG (innerhalb 14 Tage)
  ├─ FALL A: Keine Aufbewahrungspflichten → VOLLLÖSCHUNG
  │   ├─ DELETE FROM patients WHERE id = ? CASCADE
  │   ├─ DELETE FROM trips WHERE patient_id = ?
  │   ├─ Löschung aller verknüpften trip_events
  │   └─ Löschung aus Backup (nächste Rotation)
  │
  ├─ FALL B: Aufbewahrungspflichten aktiv → PSEUDONYMISIERUNG (siehe §5.1)
  │
  └─ FALL C: Rechtliche Ansprüche anhängig → SPERRUNG (Art. 18 DSGVO)
      ├─ patient.data_restricted = TRUE
      └─ Keine Verarbeitung außer für Rechtsverteidigung

SCHRITT 4 — BESTÄTIGUNG (innerhalb 1 Monat nach Antrag)
  ├─ Löschbestätigung an Patienten (Art. 19 DSGVO)
  ├─ Information aller Empfänger (Art. 19 DSGVO — soweit möglich)
  │   ├─ DeepSeek: Nicht möglich (keine Schnittstelle)
  │   ├─ Telegram: Nicht möglich (keine Admin-Rechte)
  │   └─ Krankenkasse: Information über Pseudonymisierung, sofern Abrechnungen betroffen
  └─ Eintrag im Löschprotokoll (siehe §7)
```

**Frist:** 1 Monat ab Antrag (Art. 12 Abs. 3 DSGVO). Bei Komplexität: Verlängerung auf
3 Monate mit Zwischennachricht an Patienten.

**Verantwortlich:** Datenschutzbeauftragter (DSB) oder Benannte Person.

### 4.2 Datenexport-Anforderung (vor Löschung, Art. 20 DSGVO)

Patienten haben das Recht, ihre Daten **vor** der Löschung zu exportieren
(Datenübertragbarkeit). Dies muss vor Schritt 3 angeboten werden.

**Exportformat:** Strukturiertes JSON mit allen Patientendaten + verknüpften Trips.

```json
{
  "patient": { "name": "...", "trips": [...] },
  "export_date": "2026-06-06T...",
  "retention_note": "Abrechnungsdaten werden nach §302 SGB V pseudonymisiert aufbewahrt"
}
```

### 4.3 Fahrer scheidet aus

**Auslöser:** Fahrer kündigt oder wird gekündigt → `drivers.active = FALSE`,
`drivers.ended_at = NOW()`

**Automatischer Prozess:**
```
SCHRITT 1 — Sofort: drivers.active = FALSE, drivers.ended_at = NOW()
SCHRITT 2 — Nach 3 Jahren (automatisch durch REGEL-03):
  ├─ DELETE FROM drivers WHERE id = ?
  ├─ Löschung verknüpfter driver_breaks (wenn 2-Jahres-Frist abgelaufen)
  └─ trip.driver_id bleibt erhalten (für Abrechnungsnachweise)
```

### 4.4 Ablauf der Zweckbindung

**Auslöser:** System wird außer Betrieb genommen ODER Verarbeitungszweck entfällt

**Prozess:**

```
SCHRITT 1 — Ankündigung an alle Betroffenen (Patienten, Fahrer)
SCHRITT 2 — Datenexport-Angebot an alle aktiven Nutzer
SCHRITT 3 — Datenmigration: Abrechnungsdaten ins Langzeitarchiv
SCHRITT 4 — Vollständige Löschung der Datenbank
SCHRITT 5 — Löschung aller Backups, Export-Dateien, Logs
SCHRITT 6 — Löschbestätigung an AVV-Auftragsverarbeiter (DeepSeek, Hosting)
SCHRITT 7 — Abschlussdokumentation im Löschprotokoll
```

### 4.5 Datenschutzverletzung (Art. 33/34 DSGVO)

Bei einer Datenschutzverletzung kann die Löschung kompromittierter Daten Teil der
Incident-Response sein:

```
1. Incident festgestellt → Incident-Response-Team alarmieren
2. Betroffene Datensätze identifizieren
3. Bei unbefugtem Zugriff auf S3-Daten: Sperrung + Information Aufsichtsbehörde (72h)
4. Bei Kompromittierung der DB: Vollständige DB-Prüfung + ggf. Löschung ungesicherter Kopien
5. Dokumentation im Incident-Log
```

---

## 5. Gestufte Löschung und Pseudonymisierung

### 5.1 Pseudonymisierungsverfahren bei Aufbewahrungskonflikt

**Problem:** Patient fordert Löschung (Art. 17), aber Abrechnungsdaten müssen 10 Jahre
aufbewahrt werden (§302 SGB V, §147 AO).

**Lösung:** Gestufte Löschung — klinische Daten löschen, Abrechnungsdaten pseudonymisieren.

```
STUFE 1 — DIREKTE PERSONEN-IDs LÖSCHEN
  patients.name             → "GELÖSCHT-" || substr(hex(randomblob(8)), 1, 16)
  patients.telegram_id      → NULL
  patients.phone            → NULL
  patients.default_pickup_addr → "GELÖSCHT"
  patients.default_dest_addr   → "GELÖSCHT"
  patients.vehicle_type     → NULL
  patients.special_needs    → NULL
  patients.notes            → NULL

STUFE 2 — TRIP-DATEN PSEUDONYMISIEREN
  trips.pickup_addr         → "GELÖSCHT"
  trips.dest_addr           → "GELÖSCHT"
  trips.driver_location_lat → NULL
  trips.driver_location_lon → NULL

STUFE 3 — ABRECHNUNGSDATEN BEHALTEN (pseudonymisiert)
  patients.insurance_provider  → BEHALTEN (nicht personenbezogen ohne Name)
  patients.insurance_number    → BEHALTEN (pseudonym: keine direkte Personen-ID)
  trips.fare_eur               → BEHALTEN
  trips.billing_status         → BEHALTEN

STUFE 4 — METADATEN SETZEN
  patients.deletion_requested_at    = NOW()
  patients.pseudonymized_at         = NOW()
  patients.data_retention_until     = NOW() + 10 years (für Abrechnungsfrist)
  patients.lösch_status             = 'pseudonymisiert'
```

**Ergebnis:** Patientendaten sind nicht mehr einer Person zuordenbar, aber
Abrechnungsdaten bleiben für gesetzliche Nachweispflichten erhalten.

### 5.2 Volllöschung (wenn keine Aufbewahrungspflicht)

```
-- Patient vollständig löschen (CASCADE zu trips + trip_events)
BEGIN TRANSACTION;
  DELETE FROM trip_events WHERE trip_id IN (SELECT id FROM trips WHERE patient_id = ?);
  DELETE FROM trips WHERE patient_id = ?;
  DELETE FROM recurring_trips WHERE patient_id = ?;
  DELETE FROM patients WHERE id = ?;
COMMIT;
```

**Voraussetzung:** `COUNT(trips WHERE billing_status != 'abgeschlossen') = 0`
UND 10-Jahres-Frist seit letzter Abrechnung abgelaufen.

---

## 6. Löschung in Fremdsystemen (Auftragsverarbeiter)

### 6.1 DeepSeek API (China)

**Status:** ❌ NICHT KONTROLLIERBAR
**Risiko:** Patientendaten fließen zu DeepSeek. Kein AVV vorhanden. Keine Löschschnittstelle
bekannt.

**Empfohlen:** Sofortige Migration zu einem EU-LLM (Mistral EU, Aleph Alpha, lokales
Ollama-Modell) ODER Abschluss AVV mit SCCs.

**Löschkonzept für Fremdsystem (wenn Migration nicht möglich):**
- Bei jeder Löschung: Schriftliche Weisung an DeepSeek zur Löschung aller
  verarbeiteten Patientendaten (mit Nachweis der Identität)
- Problem: DeepSeek hat kein bekanntes Data Deletion Interface
- Praktisch: Daten sind nicht löschbar → Verstoß gegen Art. 28 DSGVO

### 6.2 Telegram (UAE)

**Status:** ❌ NICHT KONTROLLIERBAR
**Risiko:** Chat-Verlauf auf Telegram-Servern. Bot kann Nachrichten nicht nachträglich
löschen (kein Admin-Zugriff auf Patientengeräte).

**Empfohlen:** In Datenschutzerklärung auf Risiko hinweisen. Migration zu
EU-Messaging-Dienst.

### 6.3 Hosting-Provider / Rechenzentrum

**Verpflichtung:** AVV §7 regelt Datenrückgabe und Löschung bei Vertragsende.
Bei laufendem Betrieb: Jährliche Bestätigung der Löschung von Backups älter als
Aufbewahrungsfrist einholen.

---

## 7. Nachweis der Löschung (Proof of Deletion)

### 7.1 Löschprotokoll-Tabelle

```sql
CREATE TABLE IF NOT EXISTS deletion_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deletion_type TEXT NOT NULL,       -- 'automatic' | 'manual_request' | 'pseudonymization' | 'system_decommission'
    data_category TEXT NOT NULL,       -- Löschklasse-ID (z.B. 'LK-S3-10Y-EV')
    table_name TEXT,                   -- betroffene DB-Tabelle
    record_count INTEGER,             -- Anzahl gelöschter/pseudonymisierter Datensätze
    record_ids TEXT,                  -- JSON-Array der gelöschten IDs (für Audit)
    patient_id INTEGER,              -- NULL wenn nicht patientenbezogen
    driver_id INTEGER,                -- NULL wenn nicht fahrerbezogen
    requested_by TEXT,                -- 'system' | 'patient' | 'driver' | 'dsb'
    requested_at TIMESTAMP,           -- Wann wurde Löschung beantragt?
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    legal_basis TEXT,                 -- Art. 17 DSGVO / §302 SGB V / etc.
    retention_override BOOLEAN DEFAULT FALSE,  -- TRUE wenn Aufbewahrungspflicht bestand
    pseudonymized BOOLEAN DEFAULT FALSE,       -- TRUE wenn pseudonymisiert statt gelöscht
    deletion_method TEXT,             -- 'DELETE CASCADE' | 'UPDATE NULL' | 'file_removal' | 'secure_overwrite'
    verified_by TEXT,                 -- Wer hat Löschung verifiziert? (manuell: Name; auto: 'system')
    notes TEXT                        -- Freitext für Sonderfälle
);
```

### 7.2 Protokollierungsregeln

| Ereignis | Was wird protokolliert |
|----------|----------------------|
| Automatische Löschung (Cron) | Löschklasse, Anzahl, IDs, Timestamp |
| Manuelle Löschung (Patientenantrag) | Vollständiger Prozess: Antrag → Prüfung → Ausführung → Bestätigung |
| Pseudonymisierung | Original-Feldwerte (Hash) + neue Werte, Begründung |
| Fehlgeschlagene Löschung | Fehlerdetails, betroffene IDs, Eskalationsstatus |
| Export-Datei-Löschung | Dateipfad, Hash vor Löschung, Löschmethode |
| AVV-Löschbestätigung | Datum der Weisung, Antwort des Auftragsverarbeiters |

### 7.3 Protokoll-Aufbewahrung

Die Löschprotokolle selbst enthalten **keine personenbezogenen Daten** (nur IDs, keine
Namen) und werden dauerhaft aufbewahrt als Nachweis der DSGVO-Compliance.

**Ausnahme:** `notes`-Feld darf keine personenbezogenen Daten enthalten (keine Namen,
Adressen, etc. — nur sachliche Begründungen).

### 7.4 Löschbestätigung an Patienten (Art. 19 DSGVO)

Bei manuellen Löschanträgen wird eine standardisierte Bestätigung an den Patienten
gesendet:

```
Betreff: Löschbestätigung — Moradbakhti-KI Krankentransport

Sehr geehrte/r [Name],

wir bestätigen die Löschung Ihrer personenbezogenen Daten aus unserem System
(gemäß Art. 17 DSGVO) mit folgenden Details:

- Antragsdatum: [Datum]
- Ausführungsdatum: [Datum]
- Umfang der Löschung: [Vollständig / Pseudonymisiert (Begründung: §302 SGB V)]
- Betroffene Datenkategorien: [Patientenstammdaten, Fahrtdaten, Kontaktdaten]
- Lösch-ID: [UUID]

Hinweis: Sofern Abrechnungsdaten noch gesetzlichen Aufbewahrungsfristen unterliegen,
wurden diese pseudonymisiert und sind nicht mehr Ihrer Person zuordenbar.

Bei Rückfragen: [DSB-Kontakt]
```

---

## 8. Technische Implementierungsspezifikation

### 8.1 Sichere Löschmethoden

| Speichermedium | Löschmethode | Standard |
|---------------|-------------|----------|
| SQLite-Datensätze | `DELETE FROM` + `VACUUM` (Freigabe des Speicherplatzes) | — |
| SQLite-Felder (Pseudonymisierung) | `UPDATE SET field = 'GELÖSCHT-...'` | — |
| Dateien auf Disk (.ogg, .csv, .pdf) | `shred -n 3 -z -u <file>` (3-faches Überschreiben + Nullen) | NIST SP 800-88 |
| Backup-Dateien | `shred -n 3 -z -u <file>` | NIST SP 800-88 |
| Log-Dateien | `rm` (keine sensitiven Daten in Logs nach 30 Tagen) | — |

### 8.2 SQLite-spezifische Besonderheiten

**WARNING:** `DELETE FROM` in SQLite markiert Speicherplatz nur als frei — die Daten
sind mit forensischen Mitteln wiederherstellbar, solange kein `VACUUM` ausgeführt wird.

**Empfohlen:**
```sql
-- Nach jeder Löschoperation:
PRAGMA secure_delete = ON;   -- Überschreibt gelöschte Daten mit Nullen
-- ODER periodisch:
VACUUM;                       -- Defragmentiert und gibt Speicherplatz frei
```

**Alternative:** `secure_delete=ON` in der SQLite-Konfiguration setzen:
```python
# In db.py / database initialization
await conn.execute_script("PRAGMA secure_delete = ON;")
```

### 8.3 Backup-Löschstrategie

Da Backups den gesamten Datenbankstand konservieren, muss nach einer Löschung das
nächste Backup den gelöschten Stand widerspiegeln. 

**Prozess:**
1. Löschung in Produktiv-DB
2. Nächstes Backup (täglich) enthält gelöschten/ pseudonymisierten Stand
3. Alte Backups: Periodisch prüfen, ob enthaltene Daten noch Aufbewahrungsfrist haben
4. Backup-Rotation: Backups älter als 10 Jahre werden mit `shred` gelöscht

---

## 9. Implementierungs-Roadmap

### 9.1 Was existiert bereits

| Komponente | Status | Details |
|-----------|--------|---------|
| Temporäre Sprachdatei-Löschung | ✅ Implementiert | `delete=True` im finally-Block |
| Telegram-Nachrichten-Verwerfung | ✅ Implementiert | Keine Persistierung, nur In-Memory-Verarbeitung |
| Löschkonzept-Dokument | ✅ Dieses Dokument | v1.0 |

### 9.2 Was muss implementiert werden (geordnet nach Priorität)

| # | Maßnahme | Prio | Aufwand | Abhängigkeit | Löschklasse |
|---|----------|------|---------|-------------|------------|
| 1 | **Datenmodell-Erweiterung:** Felder `consent_given_at`, `consent_version`, `consent_withdrawn_at`, `deletion_requested_at`, `data_retention_until`, `pseudonymized_at`, `data_restricted` zu `patients` hinzufügen | P1 | 1h | Keine | LK-S3-10Y-EV, LK-S2-3Y-CONSENT |
| 2 | **`deletion_log` Tabelle erstellen** und in DB-Schema aufnehmen | P1 | 1h | Keine | Alle |
| 3 | **`PRAGMA secure_delete = ON`** in DB-Init setzen | P1 | 0.1h | Keine | Alle |
| 4 | **Log-Rotation implementieren** (30-Tage-Frist, Cron-Job) | P1 | 2h | Keine | LK-S1-30D-LOG |
| 5 | **GPS-Nullung bei Fahrtende** im `complete_trip()` Code-Pfad | P1 | 0.5h | Keine | LK-S2-0D-LIVE |
| 6 | **Cron-Skript `scripts/deletion_cron.py`** mit allen automatisierten Löschregeln (REGEL-01 bis REGEL-11) | P1 | 4h | #1, #2 | Alle automatisierten |
| 7 | **Manueller Löschworkflow** — Admin-Interface für Patienten-Löschanträge (Identifikation → Prüfung → gestufte Löschung → Bestätigung) | P2 | 4h | #1, #2 | LK-S3-10Y-EV, LK-S3-10Y-BIL |
| 8 | **Datenexport-Funktion** (Art. 20 DSGVO) — JSON-Export vor Löschung | P2 | 2h | #1 | — |
| 9 | **Backup-Rotation** — Automatische Löschung alter Backups | P2 | 2h | #6 | LK-S3-10Y-BACKUP |
| 10 | **Export-Datei-Bereinigung** — Löschung alter CSVs/PDFs | P2 | 1h | #6 | LK-S3-10Y-EXPORT |
| 11 | **Jährlicher Lösch-Audit** — Automatisierter Report über fällige/ausgeführte/fehlgeschlagene Löschungen | P3 | 4h | #6 | Alle |
| 12 | **DeepSeek-Migration** — EU-Alternative für LLM evaluieren und migrieren | P2 | 8h | Keine | LK-S3-0D-LLM |
| 13 | **Telegram-Migration** — EU-Messaging evaluieren | P3 | 16h | Keine | LK-TRANSIENT |

### 9.3 Gesamtaufwand

| Phase | Maßnahmen | Aufwand |
|-------|----------|---------|
| **Sprint 1** (P1-Maßnahmen) | #1–#6 | ~8.6h |
| **Sprint 2** (P2-Maßnahmen) | #7–#10, #12 | ~19h |
| **Sprint 3** (P3-Maßnahmen) | #11, #13 | ~20h |
| **Gesamt** | | ~47.6h |

---

## 10. Verantwortlichkeiten

| Rolle | Verantwortung |
|-------|--------------|
| **Datenschutzbeauftragter (DSB)** | Gesamtverantwortung Löschkonzept, Freigabe manueller Löschungen, jährlicher Audit |
| **System-Administrator** | Betrieb der Cron-Jobs, Überwachung Logs, Backup-Rotation |
| **Entwickler** | Implementierung der Datenmodell-Erweiterungen, Cron-Skripte, Admin-Interface |
| **Geschäftsführung** | Ressourcen-Freigabe, Eskalation bei Compliance-Verstößen |
| **Auftragsverarbeiter (AV)** | Nachweis der Löschung nach AVV §7 |
| **Automatisiert (System)** | REGEL-01 bis REGEL-11 (Cron-gesteuert) |

### Eskalationspfad

```
Fehlgeschlagene autom. Löschung
  → deletion_errors Tabelle
    → Täglicher Check durch Admin
      → Bei >3 Tagen ungelöst: Eskalation an DSB
        → Bei >7 Tagen: Meldepflicht an Aufsichtsbehörde prüfen
```

---

## 11. Audit und Überprüfung

### 11.1 Regelmäßige Prüfungen

| Prüfung | Rhythmus | Verantwortlich |
|---------|----------|---------------|
| Löschprotokoll-Auswertung | Monatlich | DSB |
| Cron-Job-Funktionsprüfung | Wöchentlich (automatisch: Heartbeat) | System |
| Vollständiger Lösch-Audit | Jährlich | DSB + Externer Auditor |
| Aktualisierung Löschkonzept | Halbjährlich | DSB |
| AVV-Compliance-Prüfung (Auftragsverarbeiter) | Jährlich | DSB |

### 11.2 Audit-Checkliste

- [ ] Alle Cron-Jobs laufen fehlerfrei (keine Einträge in `deletion_errors`)
- [ ] `deletion_log` enthält Einträge für alle Löschklassen im Prüfzeitraum
- [ ] Keine S3-Daten in Logs (Stichprobe)
- [ ] GPS-Daten nach Fahrtende genullt (Stichprobe: `SELECT * FROM trips WHERE actual_dropoff IS NOT NULL AND (driver_location_lat IS NOT NULL)`)
- [ ] Keine abgelaufenen Backups vorhanden
- [ ] Keine abgelaufenen Export-Dateien vorhanden
- [ ] AVV-Auftragsverarbeiter haben Löschbestätigung vorgelegt
- [ ] Manuelle Löschanträge vollständig dokumentiert und innerhalb 1-Monats-Frist bearbeitet
- [ ] `secure_delete` PRAGMA aktiv (`PRAGMA secure_delete;`)

### 11.3 Kennzahlen (KPIs)

| KPI | Zielwert | Messung |
|-----|---------|---------|
| Automatische Löschquote | 100% fristgerecht | `COUNT(*) FROM deletion_log WHERE executed_at <= scheduled_at + 24h` |
| Manuelle Löschanträge in Frist | 100% ≤ 30 Tage | `AVG(executed_at - requested_at)` |
| Fehlgeschlagene Löschungen | 0 | `COUNT(*) FROM deletion_errors WHERE resolved = FALSE` |
| GPS-Daten-Leakage | 0 | `COUNT(*) FROM trips WHERE actual_dropoff IS NOT NULL AND driver_location_lat IS NOT NULL` |
| DSGVO-Compliance-Status | Grün | Audit-Checkliste 100% erfüllt |

---

## 12. Risiken und Notfallmaßnahmen

### 12.1 Risikomatrix

| Risiko | Eintrittswahrsch. | Schadenshöhe | Maßnahme |
|--------|-------------------|-------------|----------|
| DeepSeek speichert Patientendaten ohne Löschmöglichkeit | Hoch | Sehr hoch | Migration zu EU-LLM (Sprint 2) |
| Logs enthalten S3-Daten ohne Rotation | Hoch | Mittel | Log-Rotation implementieren (Sprint 1) |
| GPS-Daten verbleiben nach Fahrtende | Mittel | Mittel | GPS-Nullung implementieren (Sprint 1) |
| SQLite-Daten forensisch wiederherstellbar | Mittel | Hoch | `secure_delete=ON` + regelmäßiges `VACUUM` |
| Backup enthält gelöschte Patientendaten | Mittel | Mittel | Backup-Rotation (Sprint 2) |
| Cron-Job fällt unbemerkt aus | Niedrig | Mittel | Heartbeat-Monitoring (Teil von #6) |

### 12.2 Notfallmaßnahmen

| Szenario | Sofortmaßnahme |
|----------|---------------|
| Datenleck (Patientendaten öffentlich) | Art. 33/34 DSGVO: Meldung an Aufsichtsbehörde (72h) + Betroffene |
| Unmögliche Löschung (technischer Defekt) | Sperrung (Art. 18 DSGVO) + manuelle forensische Löschung |
| DeepSeek verweigert Löschung | Dokumentation + Aufsichtsbehörde informieren + Migration beschleunigen |
| Lösch-Cron-Job ausgefallen > 7 Tage | Manuelle Löschung + Root-Cause-Analyse |

---

## 13. Glossar

| Begriff | Definition |
|---------|-----------|
| **Löschklasse** | Gruppe von Datenkategorien mit identischem Löschtrigger und identischer Löschfrist |
| **Löschregel** | Konkrete Anweisung zur Ausführung der Löschung (manuell/automatisch, Methode) |
| **Pseudonymisierung** | Ersetzung direkter Identifikatoren durch Pseudonyme; Daten nicht mehr ohne Zusatzinformation einer Person zuordenbar |
| **Anonymisierung** | Irreversible Entfernung des Personenbezugs; keine DSGVO-Anwendbarkeit mehr |
| **Sperrung** | Einschränkung der Verarbeitung (Art. 18 DSGVO); Daten bleiben gespeichert, werden aber nicht verarbeitet |
| **Gestufte Löschung** | Mehrstufiges Verfahren: klinische Daten löschen, Abrechnungsdaten pseudonymisieren |
| **VVT** | Verzeichnis von Verarbeitungstätigkeiten (Art. 30 DSGVO) |
| **TOM** | Technische und organisatorische Maßnahmen (Art. 32 DSGVO) |
| **AVV** | Auftragsverarbeitungsvertrag (Art. 28 DSGVO) |
| **SCC** | Standardvertragsklauseln (Standard Contractual Clauses) für Drittlandtransfers |
| **DSB** | Datenschutzbeauftragter |
| **DSFA** | Datenschutz-Folgenabschätzung (Art. 35 DSGVO) |

---

## Anhang A: Checkliste für manuelle Löschanträge

Diese Checkliste ist bei JEDEM manuellen Löschantrag eines Patienten auszufüllen:

```
LÖSCHANTRAG NR: _________
DATUM ANTRAGSEINGANG: _________
KANAL: [ ] Chat  [ ] E-Mail  [ ] Telefon  [ ] Brief  [ ] Sonstiges: _________

□ 1. IDENTITÄTSPRÜFUNG
   Methode: _________
   Ergebnis: [ ] Positiv  [ ] Negativ → Abbruch

□ 2. DATENBESTAND PRÜFEN
   Patient-ID: _________
   Anzahl Trips: _________
   Offene Abrechnungen: [ ] Ja (___ Stück)  [ ] Nein
   Letzte Fahrt: _________
   Letzte Abrechnung: _________

□ 3. RECHTLICHE PRÜFUNG
   □ Abrechnungsdaten < 10 Jahre (§302 SGB V) → Pseudonymisierung
   □ Klinische Daten < 10 Jahre (§630f BGB) → Pseudonymisierung
   □ Keine Fristen → Volllöschung
   □ Rechtsstreit anhängig → Sperrung (Art. 18 DSGVO)

□ 4. DATENEXPORT ANGEBOTEN
   □ Patient möchte Export (Art. 20 DSGVO)
   □ Patient verzichtet auf Export

□ 5. AUSFÜHRUNG
   Datum: _________
   Methode: [ ] Volllöschung  [ ] Pseudonymisierung  [ ] Sperrung
   Datensätze gelöscht: _________
   Datensätze pseudonymisiert: _________

□ 6. BESTÄTIGUNG AN PATIENT
   Datum: _________
   Kanal: _________

□ 7. INFORMATION AN EMPFÄNGER (Art. 19 DSGVO)
   □ Krankenkasse informiert
   □ DeepSeek informiert (Dokumentation der erfolglosen Löschbitte)
   □ Telegram nicht informierbar (Dokumentation)
   □ Sonstige: _________

□ 8. PROTOKOLL
   Eintrag in deletion_log: _________
   Lösch-ID: _________

BEARBEITER: _________
DATUM ABSCHLUSS: _________
```

---

## Anhang B: Referenz der gesetzlichen Aufbewahrungsfristen

| Norm | Frist | Beginn | Betroffene Daten | Löschklasse |
|------|-------|--------|-----------------|------------|
| §630f Abs. 3 BGB | 10 Jahre | Ende Kalenderjahr letzte Behandlung | Patientendaten (klinisch) | LK-S3-10Y-EV |
| §302 SGB V | 10 Jahre | Ende Kalenderjahr Abrechnung | Abrechnungsdaten GKV | LK-S3-10Y-BIL |
| §304 SGB V | 10 Jahre | Ende Kalenderjahr Abrechnung | Aufbewahrungspflicht Abrechnungsdaten | LK-S3-10Y-BIL |
| §147 AO | 10 Jahre | Ende Kalenderjahr Entstehung | Steuerrelevante Unterlagen | LK-S2-10Y-FIN |
| §257 HGB | 10 Jahre | Ende Kalenderjahr Entstehung | Handelsbücher, Bilanzen | LK-S2-10Y-FIN |
| §195 BGB | 3 Jahre | Ende Kalenderjahr Entstehung | Regelverjährung (Verträge, Fahrerdaten) | LK-S2-3Y-CON |
| §199 BGB | 30 Jahre | Kenntnis des Schadens | Personenschäden (Haftung) | — (Sonderfall) |
| §16 Abs. 2 ArbZG | 2 Jahre | Ende Kalenderjahr | Arbeitszeitdokumentation | LK-S2-2Y-AZG |
| §15 Abs. 4 AGG | 6 Monate | Ab Zugang Ablehnung | Bewerbungsunterlagen | — (nicht anwendbar) |
| Art. 7 Abs. 1 DSGVO | Dauer + 3 Jahre | Ab Widerruf | Einwilligungsnachweise | LK-S2-3Y-CONSENT |
| Art. 5(1)(c) DSGVO | Sofort | Zweckerfüllung | Temporäre Dateien | LK-S3-0D-TEMP |

---

*Dokument erstellt am 06.06.2026 auf Grundlage der DATENKLASSIFIKATION.md v1.0.*
*Zuletzt geprüft: 06.06.2026*
*Nächste Überprüfung: 06.12.2026 (6-Monats-Rhythmus)*
*Geprüft durch: [Name DSB]*
