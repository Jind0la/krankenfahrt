# Tortoise Data Model — Requirements & Edge Cases Analysis

**Task:** T0.2 Datenmodell-Validierung  
**Author:** analyst  
**Date:** 2026-06-06  
**Downstream tasks:** t_bb5d29c8 (schema validation), t_7a016768 (index design)

---

## Executive Summary

Die 6 Tortoise-Modelle (Patient, Vehicle, Driver, RecurringTrip, Trip, TripEvent) decken den MVP-Happy-Path gut ab — ein Patient bucht, ein Fahrer wird zugewiesen, die Fahrt durchläuft die State Machine. Für den Produktivbetrieb in einem deutschen Krankentransport-Unternehmen fehlen jedoch kritische Felder für: Kassenabrechnung (§302 SGB V), rechtliche Nachvollziehbarkeit, Sammelfahrten, Storno-Prozesse und DSGVO-konforme Datenhaltung.

Die folgende Analyse priorisiert nach: **P1 (produktionsblockierend — ohne das kein Echteinatz), P2 (muss vor Skalierung >5 Fahrer da sein), P3 (optional/Phase 2+).**

---

## 1. Domain Context: Krankentransport in Deutschland

### 1.1 Transporttypen (real-world)

| Typ | Beschreibung | Datenmodell-Implikation |
|-----|-------------|----------------------|
| **Einzelfahrt** | Einmalige Hinfahrt A→B | Trip mit `ride_type="hin"` |
| **Hin- und Rückfahrt** | A→B, später B→A | Zwei verknüpfte Trips (`return_for` FK) oder ein Trip mit `has_return=True` |
| **Serienfahrt / Dauerfahrt** | Wiederkehrend (Dialyse Mo/Mi/Fr) | `RecurringTrip` → generiert Trip-Instanzen |
| **Sammelfahrt** | Mehrere Patienten gleichzeitig | **Aktuell nicht abbildbar** — braucht `TripGroup` oder n:m Patient↔Trip |
| **Leerfahrt** | Fahrer fährt ohne Patient (z.B. Rückfahrt) | Trip ohne Patient oder `ride_type="leer"` |

### 1.2 Fahrzeugtypen (real-world)

| Typ | P-Schein nötig | Kapazität | Besonderheiten |
|-----|---------------|-----------|----------------|
| **Sitz** (Tragestuhl) | Nein | 1 Patient + Begleitperson | Standard |
| **Liege** (Trage) | Ja | 1 Patient liegend | Braucht Liege-Platz, kein Sitz |
| **Rollstuhl** | Ja | 1-2 Rollstühle | Rampe/Lift erforderlich |
| **KTW** (Krankentransportwagen) | Ja | 1 Patient + Sanitäter | DIN EN 1789, med. Ausstattung |
| **RTW** (Rettungswagen) | Ja | 1 Patient + Notarzt | Nicht im Scope (Notfall) |

**Lücke im aktuellen Modell:** `Vehicle.vehicle_type` ist ein freies CharField — es gibt keine Validierung der erlaubten Werte und keine Unterscheidung zwischen Fahrzeug-Ausstattung (Rampe? Lift? Sauerstoff?) und Fahrzeug-Typ.

### 1.3 Abrechnungstypen

| Typ | Kostenträger | Datenmodell-Anforderung |
|-----|-------------|----------------------|
| **Krankenkasse (GKV)** | AOK, TK, Barmer, etc. | Verordnungsnummer, Genehmigung, ICD-10, Abrechnungscode |
| **Private Kasse (PKV)** | Debeka, Allianz, etc. | Rechnungsadresse, abweichender Kostenträger |
| **Berufsgenossenschaft (BG)** | BG Bau, BG Verkehr, etc. | Unfall-Nr., BG-spezifisches Formular |
| **Sozialamt** | Kommunal | Amtsbescheid, Kostenzusage |
| **Selbstzahler** | Patient direkt | Rechnungsadresse, Zahlungsstatus |

---

## 2. Use Cases & Real-World Scenarios

### UC-1: Patient registriert sich via Telegram
**Ablauf:** Patient schreibt `/start` an @FahrGast → Bot fragt Name, Adresse, Krankenkasse ab → Patient wird in DB angelegt.

**Datenmodell-Anforderungen:**
- `Patient.telegram_id` muss unique sein ✓ (bereits vorhanden)
- Adresse als strukturiertes Feld (Straße, PLZ, Ort) — aktuell `default_pickup_addr` ist freies TextField → **P1: Strukturierte Adresse nötig** für Geocoding, OSRM-Routing, Muster-4-Formular
- `insurance_provider` ist freies TextField — braucht Enum oder Referenztabelle für standardisierte KK-Namen
- **P2: Patient hat ggf. abweichende Rechnungsadresse** (z.B. Angehörige zahlen)

### UC-2: Patient bucht Einzelfahrt per Text
**Ablauf:** Patient schreibt "Morgen 8 Uhr zur Dialyse Klinikum Nord" → NLU extrahiert → Trip wird angelegt.

**Datenmodell-Anforderungen:**
- `Trip.pickup_addr` wird vom Patienten-Profil kopiert ✓
- `Trip.dest_addr` kann von NLU extrahiert sein ✓
- **P1: `Trip.ride_type` Feld fehlt** — ist es Hinfahrt, Rückfahrt, beides? Aktuell wird implizit angenommen dass jedes Trip eine Einzelfahrt ist.
- **P1: `Trip.booking_channel` Feld fehlt** — Text, Voice, Telefon (Chef händisch)? Wichtig für Fehleranalyse.

### UC-3: Patient bucht Hin- und Rückfahrt
**Ablauf:** "Morgen 8 Uhr zur Dialyse Klinikum Nord, Rückfahrt ca. 12:30" → NLU extrahiert `return_time`.

**Datenmodell-Anforderungen:**
- Aktuell: `scheduled_dropoff` kann gesetzt werden, aber es gibt kein Konzept von "Rückfahrt".
- **P1: Zwei verknüpfte Trips oder `Trip.has_return` + `Trip.return_trip_id` FK nötig.**
- Der Fahrer muss wissen: "Warte 4 Stunden oder fahr zurück?"
- Sammelfahrten: Patient A Hinfahrt 8:00, Patient B Hinfahrt 8:30, Patient A Rückfahrt 12:00, Patient B Rückfahrt 12:30.

### UC-4: Patient bucht wiederkehrende Fahrt (Dialyse)
**Ablauf:** "Jeden Mo, Mi, Fr 7:30 zur Dialyse" → `RecurringTrip` wird angelegt → Cron-Generator erzeugt täglich Trip-Instanzen.

**Datenmodell-Anforderungen:**
- `RecurringTrip.cron_days` ✓
- **P2: Ausnahmetage fehlen** — Feiertage, Praxisurlaub, Patient im Krankenhaus. Braucht `RecurringTripException` Tabelle oder `skip_dates` JSON-Feld.
- **P2: `RecurringTrip.last_generated` fehlt** — wo hat der Generator aufgehört? Wichtig bei System-Neustart.
- `RecurringTrip.active_until` ist `DateField(null=True)` ✓ — aber was passiert danach? Auto-Archivierung?
- **P2: Begrenzung der Laufzeit** — "für 12 Wochen" → braucht `max_occurrences` oder `end_date`.
- `cron_days` als Komma-String → **P3: Normalisierung** — eigene Tabelle oder JSON-Array für bessere Queryability ("alle Fahrten am Montag").

### UC-5: Disposition weist Fahrer zu
**Ablauf:** Neue Fahrt → Greedy Engine sucht besten Fahrer → Fahrer bekommt Notification.

**Datenmodell-Anforderungen:**
- `Trip.driver` nullable FK ✓
- `Driver.work_hours_start/end` ✓
- `Driver.work_days` als Komma-String — **P2: Query-Performance**: "alle Fahrer die heute arbeiten" braucht String-Parsing.
- **P1: Fahrer-Urlaub/Krankheitstage fehlen** — `Driver` braucht Abwesenheitstabelle oder `UnavailableDate` Model.
- **P1: Überlappungserkennung fehlt** — Dispatch muss wissen ob Fahrer um 9:30 noch einen anderen Trip hat. Aktuell nur TODO-Kommentar.
- **P1: Fahrer-Standort-Tracking** — `Trip.driver_location_lat/lon` wird nur im Trip gespeichert, nicht als aktuelle Fahrer-Position.
- **P2: Fahrer-Präferenzen fehlen** — manche Fahrer bevorzugen bestimmte Gebiete, Patienten, Fahrzeugtypen.

### UC-6: Fahrer-Status durch State Machine
**Ablauf:** Fahrer klickt Buttons: losfahren → angekommen → patient_an_bord → unterwegs → abgesetzt → abschliessen.

**Datenmodell-Anforderungen:**
- `Trip.status` ✓ — Statuswerte aus `TRIP_STATES`
- `TripEvent` für Audit-Log ✓
- **P1: `Trip.actual_pickup/dropoff` werden gesetzt ✓ — aber `TripEvent` speichert nicht WER den Event ausgelöst hat. Braucht `triggered_by` (driver_id, patient_id, system). Kritisches Feld für Haftung ("Fahrer hat Patient angeblich um 8:15 aufgenommen").
- **P2: Status-Timestamps** — wann genau wurde `zugewiesen` → `anfahrt` → ...? Aktuell nur über `TripEvent.created_at` rekonstruierbar. Besser: explizite `status_changed_at` am Trip.
- **P1: `Trip.distance_km` fehlt** — wie weit war die Fahrt? Wichtig für Abrechnung (km-Pauschale) und Auswertung.

### UC-7: Eskalation an Chef
**Ablauf:** Fahrer lehnt ab / Timeout / Problem → Chef bekommt Nachricht → Chef greift ein.

**Datenmodell-Anforderungen:**
- `TripEvent.event_type='problem'` ✓
- **P1: Eskalations-Status fehlt** — ist die Eskalation offen, in Bearbeitung, gelöst? Braucht `Trip.escalation_status` oder Eskalations-Tabelle.
- **P1: `TripEvent.metadata` JSON fehlt** — Eskalation braucht Kontext (welcher Fahrer hat abgelehnt? Warum?).
- **P2: Eskalations-Verlauf** — mehrere Eskalationen pro Trip möglich (Fahrer A lehnt ab → Chef weist Fahrer B zu → Fahrer B hat Panne → erneute Eskalation).

### UC-8: Patient storniert Fahrt
**Ablauf:** Patient schreibt "Fahrt morgen bitte stornieren" → NLU erkennt `cancel` → Trip auf `storniert` setzen.

**Datenmodell-Anforderungen:**
- `Trip.status='storniert'` ✓
- **P1: `Trip.cancellation_reason` fehlt** — Patient krank, Termin verschoben, kein Bedarf mehr, Fahrer zu spät. Wichtig für: Stornoquote nach Grund, Abrechnung (wer zahlt bei zu spätem Storno?).
- **P1: `Trip.cancelled_by` fehlt** — Wer hat storniert (patient, driver, chef, system)? Haftungsrelevant.
- **P1: `Trip.cancelled_at` timestamp fehlt** — wann genau wurde storniert? Wie lange vor der Fahrt?
- **P2: Storno-Gebühren-Logik** — bei Storno <24h vor Fahrt greift u.U. Ausfallpauschale. Braucht Rule Engine oder `cancellation_fee_eur`.
- **P3: Storno-Bestätigung an Patient** — automatisierte Nachricht, aber kein Datenmodell-Thema.

### UC-9: Patient ändert Fahrt (Umbuchung)
**Ablauf:** Patient will Zeit oder Ziel ändern → existierenden Trip modifizieren vs. neuen anlegen.

**Datenmodell-Anforderungen:**
- **P1: Umbuchung als Domänen-Konzept fehlt komplett.** Soll man den Trip editieren (mit Audit-Log was geändert wurde) oder alten stornieren + neuen anlegen? Beide Varianten haben Trade-offs:
  - **Edit:** Einfacher, aber: Fahrer wurde schon zugewiesen, muss ggf. neu disponiert werden → Status-Reset nötig.
  - **Storno + Neu:** Sauber, aber: Patient bekommt zwei Nachrichten, Abrechnung komplizierter.
- **P1: `Trip.modified_at` / `Trip.version` fehlt** — um Änderungen zu tracken.
- **P1: `TripEvent.event_type='modification'` mit `old_values`/`new_values` JSON** — damit nachvollziehbar ist was geändert wurde.

### UC-10: Chef exportiert Abrechnungsdaten
**Ablauf:** Chef ruft `/export 2026-06` auf → CSV aller Fahrten im Juni → lädt bei ZAD hoch.

**Datenmodell-Anforderungen:**
- `Trip.billing_status` ✓
- `Trip.fare_eur` (Float, nullable) ✓ — aber Float für Geld ist problematisch (Rundungsfehler). **P2: `Decimal` oder Integer (Cent) verwenden.**
- **P1: `Trip.billing_code` (Abrechnungsziffer) fehlt** — z.B. "KR01" für Krankentransport, "KR02" für RTW. Ohne das keine Kassenabrechnung.
- **P1: `Trip.insurance_approval` fehlt** — wurde die Fahrt von der Kasse genehmigt? Viele Fahrten brauchen Vorab-Genehmigung. Status: pending/approved/rejected/not_required.
- **P1: `Trip.transport_schein_id` fehlt** — Verknüpfung zum Transportschein (Papier/PDF), rechtlich vorgeschrieben.
- **P2: `Trip.external_invoice_id` fehlt** — wenn exportiert/bei ZAD eingereicht, welche externe ID wurde vergeben?
- **P2: `Trip.billing_exported_at` fehlt** — Zeitstempel des letzten Exports.
- **P2: Serienfahrt-Abrechnung** — Dialysefahrten werden oft als Sammelrechnung eingereicht. Braucht Batching-Konzept.

### UC-11: Sammelfahrt (Mehrere Patienten in einem Fahrzeug)
**Ablauf:** Fahrer holt Patient A (8:00), dann Patient B (8:20), fährt beide zur gleichen Klinik.

**Datenmodell-Anforderungen:**
- **P1: Aktuell NICHT abbildbar.** `Trip.patient` ist 1:1 FK. Eine Sammelfahrt braucht:
  - `TripGroup` Tabelle: `id, vehicle_id, driver_id, scheduled_start, scheduled_end, status`
  - n:m Relation `TripGroup ↔ Trip`: mehrere Trips gehören zu einer Sammelfahrt
  - ODER `Trip.parent_trip_id` self-referencing FK (Baumstruktur)
- **P2: Routen-Optimierung** — in welcher Reihenfolge werden Patienten abgeholt? Braucht `stop_order` Feld.
- **P2: Kapazitäts-Check** — `Vehicle.capacity` muss eingehalten werden.

### UC-12: Fahrer- und Fahrzeug-Stammdatenpflege
**Ablauf:** Chef legt neuen Fahrer an, weist Fahrzeug zu.

**Datenmodell-Anforderungen:**
- **P1: `Driver` hat keine Führerschein-Daten** — mindestens `driver_license_number` für Fahrerkarte.
- **P1: `Driver` hat keine Notfall-Kontaktdaten** — wer wird angerufen wenn Fahrer Unfall hat?
- **P2: `Vehicle` hat keine Wartungsdaten** — TÜV, Inspektion, Versicherung. Fällige Wartung → Fahrzeug darf nicht eingesetzt werden.
- **P2: `Vehicle` hat kein `active` Flag** — Fahrzeug in Werkstatt? Außer Betrieb?
- **P3: Fahrer-Schulungen/Zertifikate** — Ersthelfer, Fahrsicherheitstraining, Datenschutzbelehrung → Ablaufdaten tracken.

### UC-13: Patient hat besondere Bedürfnisse
**Ablauf:** Patient im Rollstuhl, braucht Rampe, Sauerstoffgerät, Begleitperson.

**Datenmodell-Anforderungen:**
- `Patient.special_needs` (TextField, nullable) ✓ — aber Freitext reicht nicht für Disposition.
- **P2: Strukturierte Special-Needs-Felder:**
  - `mobility_aid`: none | walker | wheelchair_manual | wheelchair_electric | crutches
  - `wheelchair_type`: standard | XL | electric (nur relevant wenn Rollstuhl)
  - `needs_ramp`: boolean
  - `needs_oxygen`: boolean
  - `needs_companion`: boolean (Begleitperson)
  - `needs_stretcher`: boolean (Trage statt Sitz)
  - `pflegegrad`: 0-5 (Pflegegrad für Abrechnung relevant)
- **P3: Patientengewicht** — für Fahrzeug-Tragfähigkeit (z.B. Schwerlast-Rollstuhl).

### UC-14: GDPR / DSGVO Compliance
**Ablauf:** Patient verlangt Löschung seiner Daten, Aufsichtsbehörde prüft.

**Datenmodell-Anforderungen:**
- **P1: `Patient` braucht `data_retention_until` oder `deletion_requested_at`** — DSGVO Art. 17: Recht auf Löschung.
- **P1: Personenbezogene Daten müssen von abrechnungsrelevanten Daten trennbar sein** — Name/Adresse/Telefon in `Patient`, aber Abrechnungsdaten (Trip-Verlauf) müssen X Jahre aufbewahrt werden → Pseudonymisierung nötig.
- **P2: `Patient` braucht `consent_given_at` + `consent_version`** — Einwilligung zur Datenverarbeitung (DSGVO Art. 6).
- **P2: `TripEvent` protokolliert personenbezogene Änderungen → muss bei Patient-Löschung mitgelöscht oder pseudonymisiert werden.**
- **P3: Data Processing Agreement (AVV) Logging** — welche Subprozessoren hatten Zugriff?

---

## 3. Edge Cases — Detaillierte Analyse

### 3.1 Storno (Cancellation)

| # | Szenario | Trigger | Datenmodell-Anforderung | Prio |
|---|----------|---------|------------------------|------|
| SC1 | Patient storniert vor Fahrer-Zuweisung | Patient via Bot | `status=storniert`, `cancelled_by=patient`, `cancelled_at=now()` | P1 |
| SC2 | Patient storniert nach Fahrer-Zuweisung | Patient via Bot | Fahrer muss benachrichtigt werden dass Fahrt wegfällt. `TripEvent` mit `event_type=cancellation` und `triggered_by=patient_id`. | P1 |
| SC3 | Patient storniert während Fahrer unterwegs ist | Patient via Bot | Fahrer ist schon losgefahren → Leerfahrt-Kosten? Wer trägt sie? `cancellation_fee_eur` Feld nötig. | P2 |
| SC4 | Fahrer storniert (krank, Unfall) | Fahrer via Bot | `status` zurück auf `geplant`, `driver=null` — Dispatch Engine sucht neuen Fahrer. `TripEvent` mit `reason`. | P1 |
| SC5 | Fahrer erscheint nicht (Timeout) | System (Timer) | Kein Status-Update innerhalb X Minuten → Eskalation an Chef. Braucht `last_status_change` Timestamp am Trip. | P1 |
| SC6 | Chef storniert (höhere Gewalt) | Chef via Bot | `cancelled_by=chef`, `cancellation_reason="Wetter/Unfall/..."`. Patient automatisch benachrichtigen. | P1 |
| SC7 | Patient storniert nur Rückfahrt | Patient via Bot | Wenn Trip als Roundtrip modelliert ist: nur ein Teil wird storniert. `return_trip` separat stornierbar. ODER: Ein Trip für Hin- und Rückfahrt → `ride_type` ändern. | P1 |
| SC8 | Storno einer wiederkehrenden Fahrt | Patient via Bot | Einzelne Instanz stornieren vs. gesamte Serie beenden. `RecurringTrip.active_until` = heute setzen. | P2 |
| SC9 | Storno <24h vor Fahrt (Ausfallpauschale) | System erkennt | Business-Logik: `cancellation_fee_eur` berechnen, `billing_status` auf `ausfallpauschale`. | P2 |
| SC10 | Massenstorno (Praxis schließt, alle Dialysefahrten fallen aus) | Chef händisch | Batch-Operation nötig: alle Trips für Patienten an Ziel X stornieren. Kein Schema-Problem, sondern API-Design. | P3 |

### 3.2 Umbuchung (Rebooking / Modification)

| # | Szenario | Datenmodell-Anforderung | Prio |
|---|----------|------------------------|------|
| UB1 | Zeitänderung (8:00 → 8:30) | `scheduled_pickup` ändern, `TripEvent` mit `event_type=modification` und `old_time`/`new_time` in `metadata`. Fahrer prüfen: Kollision mit anderen Fahrten? Ggf. neu disponieren → `status=geplant`, `driver=null`. | P1 |
| UB2 | Zieländerung (Klinikum Nord → Klinikum Süd) | `dest_addr` ändern. Fahrzeit neu berechnen → `scheduled_dropoff` updaten. `estimated_duration` / `estimated_distance` aktualisieren. | P1 |
| UB3 | Fahrzeugtyp-Änderung (Sitz → Liege) | Patient ist heute bettlägerig → `vehicle_type` am Trip ändern. Check: aktueller Fahrer/Fahrzeug kann Liege? Sonst neu disponieren. | P2 |
| UB4 | Fahrer-Wechsel während Fahrt (Panne, Krankheit) | Fahrer A meldet Problem → Chef weist Fahrer B zu → `driver=B`, `TripEvent` mit `reason="driver_switch"`. | P1 |
| UB5 | Wiederkehrende Fahrt: Template ändern | Mo/Mi/Fr → Mo/Do. `RecurringTrip.cron_days` updaten. Bereits generierte zukünftige Trips: löschen und neu generieren oder einzeln updaten? Design-Entscheidung nötig. | P2 |
| UB6 | Wiederkehrende Fahrt: Einzelne Instanz abweichend | "Nächsten Mittwoch erst 9:00 statt 8:00". Einzelne Trip-Instanz editieren, Template unverändert lassen. `Trip.overrides_template=True` Flag, damit Generator die Instanz nicht überschreibt. | P2 |
| UB7 | Adresse des Patienten ändert sich dauerhaft | `Patient.default_pickup_addr` updaten → alle zukünftigen generierten Trips sollten neue Adresse verwenden. Bereits disponierte Trips: manuelles Update oder Auto-Propagation? Design-Entscheidung. | P2 |

### 3.3 Teilrückerstattung / Billing Edge Cases

| # | Szenario | Datenmodell-Anforderung | Prio |
|---|----------|------------------------|------|
| TR1 | Fahrer zu spät, Patient nimmt Taxi | Trip wurde nicht durchgeführt, aber Kosten sind entstanden. `status=storniert`, `cancellation_reason="driver_late"`. Ob Erstattung fällig ist, ist Business-Logik — aber Daten müssen den Fall abbilden. | P2 |
| TR2 | Falscher Fahrzeugtyp (Sitz statt Liege) | Trip wurde durchgeführt, aber Patient beschwert sich. `billing_status` = `disputed` oder `teilrechnung`. `fare_eur` mit Rabatt überschreiben. | P2 |
| TR3 | Patient steigt unterwegs aus (Notfall) | `status=aborted`, `actual_dropoff` = Zeitpunkt des Abbruchs. Abrechnung der Teilstrecke: `billing_status=teilabrechnung`, `distance_km` für gefahrene Teilstrecke. | P2 |
| TR4 | Kasse lehnt Abrechnung ab | Genehmigung fehlte / Formfehler. `insurance_approval=rejected`, Eskalation an Chef: selbst zahlen lassen oder korrigieren? | P2 |
| TR5 | Kilometergeld-Erstattung (privat) | Patient fährt mit privatem PKW, will Km-Geld. Kein klassischer Trip, sondern `ExpenseReport`? Nicht im aktuellen Scope. | P3 |

### 3.4 Complex Scheduling Edge Cases

| # | Szenario | Datenmodell-Anforderung | Prio |
|---|----------|------------------------|------|
| CS1 | Sommerzeit/Winterzeit-Umstellung | März: 02:00→03:00 (eine Stunde weniger). Oktober: 03:00→02:00 (eine Stunde mehr). Trips in der kritischen Nacht: doppelte 02:30-Zeit im Oktober. `scheduled_pickup` sollte UTC sein oder explizit Timezone tragen. **Aktuell: Naive Datetime ohne TZ — Bug!** | P1 |
| CS2 | Feiertage (länderspezifisch!) | Wiederkehrende Fahrt an Fronleichnam (nicht in allen Bundesländern Feiertag). `RecurringTrip` braucht `skip_on_holidays` Flag + Länder-Zuordnung. | P2 |
| CS3 | Patient wartet nicht (No-Show) | Fahrer wartet X Minuten, Patient kommt nicht. `status=no_show` (neuer Status nötig?). Stornogebühr? Benachrichtigung an Patient? | P2 |
| CS4 | Fahrer wartet übermäßig lange | Patient ist 30 Min zu spät, Fahrer wartet. `actual_pickup` viel später als `scheduled_pickup`. `wait_time_minutes` für Fahrer-Abrechnung (Wartezeit wird z.T. vergütet). | P2 |
| CS5 | Überschneidende Fahrten eines Patienten | Patient hat 8:00 Dialyse und 8:30 Physio gebucht — Double-Booking Detection nötig. Constraint: keine zwei aktiven Trips mit überlappenden Zeiten für denselben Patienten. | P2 |
| CS6 | Fahrer am Ende der Schicht, Fahrt dauert länger | Schichtende 16:00, aber Fahrt ist um 15:45 gestartet und dauert bis 16:30. `Driver`-Verfügbarkeit: nur START der Fahrt muss in Arbeitszeit liegen? Oder komplette Fahrt? Design-Entscheidung. | P2 |
| CS7 | Fahrer fährt Patienten an falsche Adresse | `dest_addr` vs. tatsächliches Ziel. `TripEvent` mit `event_type=incident` und Korrektur. Audit Trail essenziell. | P2 |

---

## 4. Data Integrity & Constraints

### 4.1 Fehlende Constraints im aktuellen Schema

| Constraint | Betroffene(s) Model | Begründung | Prio |
|-----------|-------------------|-----------|------|
| `Patient.telegram_id` UNIQUE | Patient | ✓ Vorhanden | — |
| `Patient.insurance_provider` NOT NULL wenn `insurance_number` gesetzt | Patient | Halbe KK-Daten sind nutzlos für Abrechnung | P2 |
| `Driver` → `Vehicle` 1:1 (nicht 1:n) | Driver | Ein Fahrer hat genau ein Fahrzeug pro Schicht. Wenn Fahrer-Wechsel: Update der FK, nicht mehrere. Aktuell: `null=True` — ok, aber kein Constraint dass ein Fahrzeug nur einen aktiven Fahrer hat. | P2 |
| `Trip.scheduled_pickup` < `Trip.scheduled_dropoff` (wenn `dropoff != null`) | Trip | Logische Konsistenz: Dropoff muss nach Pickup sein | P1 |
| `Trip.status` nur erlaubte Werte | Trip | ✓ Über State Machine enforced, aber DB-Level Constraint fehlt → bei direkter DB-Manipulation kaputt | P2 |
| `Trip.patient` NOT NULL | Trip | Eine Fahrt ohne Patient ist eine Leerfahrt — sollte explizit markiert sein, nicht über nullable FK | P1 |
| `Trip.billing_status` nur erlaubte Werte | Trip | Enum: offen, exportiert, abgerechnet, storniert, disputed | P2 |
| `Vehicle.license_plate` UNIQUE | Vehicle | ✓ Vorhanden | — |
| `Vehicle.vehicle_type` CHECK constraint | Vehicle | Nur erlaubte Werte: Sitz, Liege, Rollstuhl, KTW | P2 |
| Kein gleichzeitiges `actual_pickup` und `actual_dropoff` für inkompatible Status | Trip | Bei `status=geplant` sollte `actual_pickup` immer NULL sein | P2 |

### 4.2 Fehlende Indices (für Query-Performance)

*Detaillierte Index-Analyse ist Aufgabe von t_7a016768. Hier nur die Query-Patterns, aus denen Indices abgeleitet werden sollten:*

| Query Pattern | Häufigkeit | Betroffene Felder |
|--------------|-----------|------------------|
| Alle aktiven Trips eines Fahrers heute | Hoch (jede Status-Änderung) | `Trip.driver_id + Trip.status + Trip.scheduled_pickup` |
| Alle Fahrten eines Patienten (History) | Mittel (Patient fragt "meine Fahrten") | `Trip.patient_id + Trip.created_at` |
| Offene Fahrten für Disposition (geplant, ohne Fahrer) | Hoch (Dispatch-Loop, Dashboard) | `Trip.status + Trip.scheduled_pickup` |
| Fahrer-Verfügbarkeit: alle Fahrten in Zeitfenster | Hoch (Dispatch Engine) | `Trip.driver_id + Trip.scheduled_pickup + Trip.scheduled_dropoff` |
| Wiederkehrende Fahrten für Generator | Mittel (Cron täglich) | `RecurringTrip.active_until + RecurringTrip.last_generated` |
| Abrechnung: alle Fahrten in Zeitraum mit Status | Mittel (Monats-Export) | `Trip.billing_status + Trip.scheduled_pickup` |
| Alle aktiven Fahrer | Hoch (Dispatch Engine) | `Driver.active + Driver.work_days + Driver.work_hours_start` |
| Fahrzeug-Verfügbarkeit | Mittel (Dispatch Engine) | `Vehicle.id + Trip.vehicle_id + Trip.status` |

---

## 5. Missing Domain Entities

### 5.1 Vorgeschlagene neue Modelle

| Modell | Zweck | Felder | Prio |
|--------|-------|--------|------|
| **Address** | Strukturierte Adresse statt TextField | `street`, `postal_code`, `city`, `lat`, `lon`, `google_place_id` | P1 |
| **InsuranceProvider** | Referenztabelle Krankenkassen | `name`, `ik_number` (Institutionskennzeichen), `billing_portal` | P2 |
| **DriverAbsence** | Urlaub, Krankheit, Fortbildung | `driver_id`, `start`, `end`, `reason` (vacation/sick/training) | P1 |
| **TripGroup** | Sammelfahrt-Gruppe | `id`, `vehicle_id`, `driver_id`, `scheduled_start`, `status` | P1 |
| **TripGroupMember** | n:m Trip ↔ TripGroup | `trip_group_id`, `trip_id`, `stop_order` | P1 |
| **RecurringTripException** | Ausnahmen für wiederkehrende Fahrten | `recurring_trip_id`, `date`, `reason` | P2 |
| **TransportDocument** | Verknüpfung zu Transportschein/PDF | `trip_id`, `document_type` (muster4/bg/private), `file_path`, `external_id` | P1 |
| **InsuranceApproval** | Genehmigungsstatus pro Trip | `trip_id`, `status` (pending/approved/rejected), `approved_by`, `valid_until`, `reference_number` | P1 |
| **Company** | Multi-Tenancy Vorbereitung | `name`, `billing_address`, `tax_id`, `ik_number` | P3 |
| **AuditLog** (Erweiterung TripEvent) | Generisches Audit für ALLE Modelle | `table_name`, `row_id`, `action` (create/update/delete), `changed_by`, `old_values` (JSON), `new_values` (JSON) | P2 |

---

## 6. Priority Summary

### P1 — Produktionsblockierend (MVP kann ohne das nicht live gehen)

1. **Strukturierte Adressen** (Address-Embedded oder eigene Tabelle) — Geocoding, OSRM, Muster-4
2. **Ride-Type** (`ride_type`: hin, rück, beide, leer) — sonst keine korrekte Abrechnung
3. **Hin- und Rückfahrt Verknüpfung** (`return_trip_id` FK) — essenziell für Dialyse-Fahrten
4. **Storno-Felder** (`cancelled_by`, `cancelled_at`, `cancellation_reason`) — Haftung & Compliance
5. **Umbuchungs-Audit** (`TripEvent` mit `triggered_by`, `metadata` JSON) — Nachvollziehbarkeit
6. **Fahrer-Abwesenheiten** (`DriverAbsence`) — sonst bekommen kranke Fahrer Aufträge
7. **Abrechnungsfelder** (`billing_code`, `insurance_approval`, `transport_schein_id`) — ohne das keine Kassenabrechnung
8. **Sammelfahrt-Modelle** (`TripGroup` + `TripGroupMember`) — reale Anforderung, aktuell nicht abbildbar
9. **Timezone-Aware Datetimes** — `scheduled_pickup` muss UTC oder timezone-aware sein (Sommerzeit-Bug)
10. **`Trip.distance_km`** — für km-basierte Abrechnung und Auswertung

### P2 — Vor Skalierung (>5 Fahrer) nötig

1. Deckt alle verbleibenden Edge-Case-Felder aus §3 ab
2. InsuranceProvider-Referenztabelle
3. Vehicle-Wartungsdaten (TÜV, Inspektion)
4. Strukturierte Special-Needs (Rollstuhl-Typ, Rampe, Sauerstoff)
5. RecurringTrip-Ausnahmen (Feiertage, Urlaub)
6. Float → Decimal für Geldbeträge
7. DB-Level CHECK Constraints
8. Generisches AuditLog-Modell

### P3 — Optional / Phase 2+

1. Multi-Tenancy (Company-Modell)
2. Fahrer-Schulungs-Zertifikate
3. Patientengewicht / Schwerlast-Rollstuhl
4. Kilometergeld-Erstattung (Privat-PKW)
5. Massenstorno-Tooling
6. `cron_days` Normalisierung (JSON statt Komma-String)

---

## 7. Design Decisions (Offen)

Folgende Punkte brauchen eine explizite Entscheidung, weil sie Architektur-Implikationen haben:

| # | Frage | Optionen | Empfehlung |
|---|-------|----------|-----------|
| D1 | Hin- und Rückfahrt: ein Trip oder zwei verknüpfte Trips? | A) Ein Trip mit `has_return` und `return_pickup_time` B) Zwei Trips mit `return_for` FK | **A** für einfache Fälle, **B** für Abrechnung — Kombination: `Trip.is_return` + `Trip.outbound_trip_id` |
| D2 | Umbuchung: Trip editieren oder storno+neu? | A) Trip editieren mit Audit-Log B) Alten stornieren, neuen anlegen | **A** — weniger Benachrichtigungen, bessere UX. Erfordert `Trip.version` und robustes `TripEvent`-Logging. |
| D3 | Sammelfahrt: explizite `TripGroup` Tabelle oder self-referencing FK? | A) `TripGroup` + `TripGroupMember` B) `Trip.parent_trip_id` (Baum) | **A** — klarer, query-bar, einfacher für OR-Tools Integration. |
| D4 | Adressen: Embedded im Patient/Trip oder eigene Tabelle? | A) `street/city/zip/lat/lon` Felder direkt B) Eigene `Address` Tabelle mit FK | **A** für MVP (einfacher), **B** für Skalierung (Wiederverwendung, Normalisierung). Empfehlung: A für Patient, mit Pfad zu B über Migration. |
| D5 | Zeitstempel: UTC in DB, Lokalzeit in App-Logik? | A) Alles UTC, App wandelt um B) Timezone-aware in DB | **A** — Standard, weniger Bugs, DB-unabhängig. Aber: `scheduled_pickup` MUSS UTC sein, aktuell ist es naiv. |
| D6 | Geldbeträge: `Decimal` oder Integer-Cents? | A) `DecimalField` B) `IntegerField` (Cent) | **A** — Tortoise/Pydantic unterstützen Decimal gut. Integer-Cents sind fehleranfällig bei Division. |

---

## 8. Migration Strategy Notes

Da SQLite verwendet wird (kein PostgreSQL-`ALTER TABLE` mit minimalem Locking), sind Schema-Migrationen potenziell destruktiv. Empfehlung:

1. **Phase 0 (jetzt):** Alle P1-Felder zu den existierenden Tabellen hinzufügen, BEVOR Produktivdaten existieren.
2. **Phase 1:** Neue Tabellen (`TripGroup`, `DriverAbsence`, `InsuranceApproval`) anlegen — unkritisch.
3. **Phase 2:** `Address`-Embedded-Felder zu `Patient` und `Trip` hinzufügen, alte `TextField`-Adressen parallel lassen, später deprecaten.
4. **Aerich** (Tortoise-Migration-Tool) evaluieren für automatisierte Migrations— aktuell nicht in dependencies.

---

*Ende der Analyse. Nächste Schritte: t_bb5d29c8 validiert das Schema gegen diese Anforderungen, t_7a016768 entwirft Indices basierend auf den Query-Patterns in §4.2.*
