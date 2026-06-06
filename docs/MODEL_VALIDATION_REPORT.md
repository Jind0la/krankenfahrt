# Tortoise Data Model Validation Report

**Task:** T0.2 Datenmodell-Validierung  
**Author:** analyst  
**Date:** 2026-06-06  
**Source:** schema.py (6 models, 137 lines) validated against REQUIREMENTS_EDGE_CASES.md (14 use cases, 30 edge cases, 10 P1 gaps)

---

## Executive Summary

**Verdict: 3/6 models production-ready with gaps. Trip is the most broken — 7 of 10 P1 gaps land there.**

The current schema handles the MVP Happy Path (Patient → Book → Dispatch → Drive → Complete) adequately. For a German Krankentransport business operating under §302 SGB V, the gaps are concentrated in:

| Model | Fields Present | P1 Gaps | P2 Gaps | Verdict |
|-------|---------------|---------|---------|---------|
| **Patient** | 10 | 2 (address struct, DSGVO retention) | 4 (billing addr, consent, structured needs, pflegegrad) | Needs structured address + DSGVO fields |
| **Vehicle** | 5 | 0 | 2 (maintenance, active flag) | Lean but sufficient for MVP |
| **Driver** | 7 | 2 (absence tracking, license number) | 2 (emergency contact, preferences) | Missing absence model — dispatch breaks |
| **RecurringTrip** | 9 | 1 (last_generated missing) | 4 (exceptions, holidays, max_occurrences, cron_days normalized) | Works for MVP with manual oversight |
| **Trip** | 17 | 7 (ride_type, return trip, storno fields, billing_code, distance_km, timezone, transport_schein) | 10 | **Most broken — needs 7 fields to go live** |
| **TripEvent** | 4 | 2 (triggered_by, metadata JSON) | 1 (generic audit) | **Critically incomplete for compliance** |

**Bottom line:** To go live in Germany, Trip needs 7 additional fields, TripEvent needs 2, and 4 new tables (Address, DriverAbsence, TripGroup, TripGroupMember, TransportDocument, InsuranceApproval) must exist.

---

## 1. Patient — Gap Analysis

### 1.1 Fields Present vs. Required

| Field | Type | Status | Gap |
|-------|------|--------|-----|
| `telegram_id` | BigIntField, unique | ✅ | — |
| `name` | CharField(200) | ✅ | — |
| `phone` | CharField(50), nullable | ✅ | — |
| `default_pickup_addr` | TextField | ⚠️ P1 | Unstructured text — no geocoding possible |
| `default_dest_addr` | TextField, nullable | ⚠️ P2 | Same as above |
| `insurance_provider` | CharField(200), nullable | ⚠️ P2 | Free text — no validation, no IK-Nummer ref |
| `insurance_number` | CharField(50), nullable | ⚠️ P2 | No constraint: if set, provider must be set |
| `vehicle_type` | CharField(20), default="Sitz" | ⚠️ P2 | No CHECK constraint — accepts any string |
| `special_needs` | TextField, nullable | ⚠️ P2 | Free text — dispatch can't filter on it |
| `notes` | TextField, nullable | ✅ | — |
| `created_at` | DatetimeField, auto_now_add | ✅ | — |

### 1.2 Missing Fields

| Field | Priority | Rationale |
|-------|----------|-----------|
| **Structured address** (street, postal_code, city, lat, lon) | P1 | Geocoding, OSRM routing, Muster-4-Formular. Design decision D4 recommends embedded fields for MVP |
| `data_retention_until` / `deletion_requested_at` | P1 | DSGVO Art. 17 — patient must be able to request deletion |
| `billing_address` (separate from pickup) | P2 | UC-1: patient may have different billing address (e.g. relatives pay) |
| `consent_given_at` + `consent_version` | P2 | DSGVO Art. 6 — proof of consent for data processing |
| Structured special needs (mobility_aid, wheelchair_type, needs_ramp, needs_oxygen, needs_companion, needs_stretcher) | P2 | UC-13: dispatch must filter drivers/vehicles by patient needs |
| `pflegegrad` (0-5) | P2 | Abrechnungsrelevant |
| `date_of_birth` | P2 | Required for Muster-4 invoice (patient_geburtsdatum) |

### 1.3 Constraint Gaps

| Constraint | Priority | Notes |
|-----------|----------|-------|
| `insurance_provider` NOT NULL when `insurance_number` is set | P2 | Half KK-data is useless for billing |
| `vehicle_type` CHECK IN ('Sitz', 'Liege', 'Rad', 'KTW') | P2 | Current: any string accepted |

---

## 2. Vehicle — Gap Analysis

### 2.1 Fields Present vs. Required

| Field | Type | Status | Gap |
|-------|------|--------|-----|
| `license_plate` | CharField(20), unique | ✅ | — |
| `vehicle_type` | CharField(20), default="Sitz" | ⚠️ P2 | Same CHECK gap as Patient |
| `capacity` | IntField, default=1 | ✅ | But unused — no Sammelfahrt model yet |
| `notes` | TextField, nullable | ✅ | — |

### 2.2 Missing Fields

| Field | Priority | Rationale |
|-------|----------|-----------|
| `active` (Boolean) | P2 | Vehicle in repair shop? Decommissioned? Dispatch must know |
| `tuev_until` (Date) | P2 | TÜV expiry — vehicle cannot operate without valid inspection |
| `inspection_until` (Date) | P2 | Regular maintenance deadline |
| `insurance_until` (Date) | P2 | Vehicle insurance expiry |
| `equipment` (JSON or flags for ramp, lift, oxygen) | P2 | UC-13: dispatch needs to match vehicle equipment to patient needs |

### 2.3 Constraint Gaps

| Constraint | Priority | Notes |
|-----------|----------|-------|
| `vehicle_type` CHECK IN ('Sitz', 'Liege', 'Rad', 'KTW') | P2 | — |
| `capacity` >= 1 CHECK | P2 | Negative capacity is nonsensical |

**Verdict:** Vehicle is the healthiest model. 5 simple fields, unique constraint on license_plate. Only missing operational flags.

---

## 3. Driver — Gap Analysis

### 3.1 Fields Present vs. Required

| Field | Type | Status | Gap |
|-------|------|--------|-----|
| `telegram_id` | BigIntField, unique | ✅ | — |
| `name` | CharField(200) | ✅ | — |
| `phone` | CharField(50) | ✅ | — |
| `p_schein` | BooleanField, default=False | ✅ | Used in dispatch properly |
| `work_hours_start` | TimeField, default="07:00" | ✅ | — |
| `work_hours_end` | TimeField, default="16:00" | ✅ | — |
| `work_days` | CharField(50), "Mo,Di,Mi,Do,Fr" | ⚠️ P2 | Comma-string — dispatch does substring matching (fragile) |
| `active` | BooleanField, default=True | ✅ | — |
| `vehicle` | FK → Vehicle, nullable | ✅ | — |

### 3.2 Missing Fields

| Field | Priority | Rationale |
|-------|----------|-----------|
| **DriverAbsence table** (separate model) | P1 | Without it, sick drivers get dispatched. UC-5, UC-12 |
| `driver_license_number` | P1 | Legal requirement for vehicle operation |
| `emergency_contact_name` + `emergency_contact_phone` | P2 | UC-12: who to call if driver has accident |
| `preferred_areas` (JSON or text) | P3 | Some drivers prefer certain districts |
| `certifications` (JSON or separate table) | P3 | First aid, safety training, data protection — with expiry dates |

### 3.3 Code-Level Issues Found

**dispatch.py:103** — `day_name not in driver.work_days` does substring matching:
```python
day_name = trip.scheduled_pickup.strftime("%a")[:2]  # "Mo", "Di"
if day_name not in driver.work_days:  # "Mo,Di,Mi,Do,Fr"
```
This is **buggy**: "Mo" would match a string containing "Mo" anywhere (e.g. "Sa,So" → "So" matched → false positive? Actually no — `strftime("%a")[:2]` gives "Sa" for Saturday, "So" for Sunday on German locale). But "Do" (Thursday) also matches if work_days contains "Do" as a substring of "Sa,Do" — wait, "Do" is NOT a substring of "Sa,So". The actual risk: on a German system, `strftime("%a")` returns "Mo", "Di", "Mi", "Do", "Fr", "Sa", "So". The substring check `"Do" in "Mo,Di,Mi,Do,Fr"` works. But `"Do" in "Mo,Do,Mi"` also works because "Do" is a substring of "Do". The real bug: `"So"` (Sunday) could match `"So"` as a substring of... well, no German day ends in "So" except "So" itself.

BUT there's a locale dependency: `strftime("%a")` behavior depends on system locale. On non-German systems, it might return "Mon", "Tue", etc. The dispatch code then looks for "Mo" in "Mo,Di,Mi,Do,Fr" — which works because German abbreviations are stored. But if locale is English, strftime returns "Mon" and `[:2]` gives "Mo" — which would still work. But "Thu" → "Th" won't match "Do". **This is a locale bug waiting to happen.**

**Recommendation:** Normalize `work_days` to a JSON array or a separate DriverWorkDay table.

### 3.4 Constraint Gaps

| Constraint | Priority | Notes |
|-----------|----------|-------|
| `work_hours_start` < `work_hours_end` | P3 | Logical consistency |
| `phone` NOT NULL | ✅ Present | — |

---

## 4. RecurringTrip — Gap Analysis

### 4.1 Fields Present vs. Required

| Field | Type | Status | Gap |
|-------|------|--------|-----|
| `patient` | FK → Patient | ✅ | — |
| `pickup_addr` | TextField | ⚠️ P1 | Inherits address problem from Patient |
| `dest_addr` | TextField | ⚠️ P1 | Same |
| `cron_days` | CharField(50) | ⚠️ P3 | Comma-string — poor queryability |
| `pickup_time` | TimeField | ✅ | — |
| `return_time` | TimeField, nullable | ✅ | — |
| `vehicle_type` | CharField(20) | ⚠️ P2 | Same CHECK gap |
| `active_until` | DateField, nullable | ✅ | — |
| `created_at` | DatetimeField, auto_now_add | ✅ | — |

### 4.2 Missing Fields

| Field | Priority | Rationale |
|-------|----------|-----------|
| **`last_generated`** (DateTime) | P1 | Generator must know where it left off after system restart — UC-4 |
| `skip_on_holidays` (Boolean) | P2 | German public holidays vary by state — CS2 |
| `holiday_state` (CharField, e.g. "BY", "NW") | P2 | Which state's holiday calendar to use |
| `max_occurrences` (IntField) | P2 | "For 12 weeks" — UC-4 |
| `end_date` (DateField, alternative to active_until) | P2 | Already have `active_until` — decide which |

### 4.3 Missing Table

| Table | Priority | Rationale |
|-------|----------|-----------|
| **RecurringTripException** (date, reason, FK to RecurringTrip) | P2 | UC-4: holidays, practice closures, patient in hospital |

**Verdict:** Works for MVP but `last_generated` is a P1 blocker — without it, generator restarts produce duplicate trips.

---

## 5. Trip — Gap Analysis (MOST BROKEN)

### 5.1 Fields Present vs. Required

| Field | Type | Status | Gap |
|-------|------|--------|-----|
| `patient` | FK → Patient | ✅ | But 1:1 — no Sammelfahrt possible |
| `driver` | FK → Driver, nullable | ✅ | — |
| `vehicle` | FK → Vehicle, nullable | ✅ | — |
| `recurring_template` | FK → RecurringTrip, nullable | ✅ | — |
| `pickup_addr` | TextField | ⚠️ P1 | Same address problem |
| `dest_addr` | TextField | ⚠️ P1 | Same |
| `scheduled_pickup` | DatetimeField | 🔴 P1 | **NAIVE datetime — no timezone. Sommerzeit-Bug!** |
| `scheduled_dropoff` | DatetimeField, nullable | 🔴 P1 | Same timezone issue |
| `actual_pickup` | DatetimeField, nullable | 🔴 P1 | Same + no constraint: must be NULL when status is 'geplant' |
| `actual_dropoff` | DatetimeField, nullable | 🔴 P1 | Same |
| `status` | CharField(30), default="geplant" | ⚠️ P2 | No DB-level CHECK constraint |
| `billing_status` | CharField(20), default="offen" | ⚠️ P2 | No CHECK constraint |
| `fare_eur` | FloatField, nullable | ⚠️ P2 | **Float for money — rounding errors. Use Decimal.** |
| `driver_location_lat` | FloatField, nullable | ⚠️ P2 | Driver position on Trip, not on Driver — wrong place for real-time tracking |
| `driver_location_lon` | FloatField, nullable | ⚠️ P2 | Same |
| `created_at` | DatetimeField, auto_now_add | ✅ | — |

### 5.2 Missing Fields (P1 — Production Blocker)

| # | Field | Type | Rationale |
|---|-------|------|-----------|
| 1 | **`ride_type`** | CharField(20) | Enum: 'hin', 'rueck', 'beide', 'leer'. Without this, billing and dispatch can't distinguish trip types (UC-2) |
| 2 | **`return_trip_id`** | FK → Trip, nullable | Link outbound/return trips. UC-3: patient books Hin- und Rückfahrt |
| 3 | **`cancelled_by`** | CharField(20) | 'patient', 'driver', 'chef', 'system'. Haftungsrelevant (UC-8, SC1-SC10) |
| 4 | **`cancelled_at`** | DatetimeField | When exactly was it cancelled? SC1 requires timestamp |
| 5 | **`cancellation_reason`** | TextField | Why cancelled? For Storno-Analyse (SC3, SC6, SC9) |
| 6 | **`distance_km`** | FloatField | How far was the trip? km-Pauschale billing (UC-6) |
| 7 | **`billing_code`** | CharField(20) | Abrechnungsziffer: 'KR01', 'KR02', etc. Without this, no Kassenabrechnung (UC-10) |
| 8 | **`booking_channel`** | CharField(20) | 'text', 'voice', 'phone'. For error analysis (UC-2) |
| 9 | **`status_changed_at`** | DatetimeField | When did status last change? For timeout detection (SC5) |
| 10 | **Timezone-aware datetimes** | N/A | `scheduled_pickup` must store UTC or be timezone-aware. Sommerzeit-Bug (CS1) |

### 5.3 Missing Fields (P2 — Before Scaling)

| # | Field | Type | Rationale |
|---|-------|------|-----------|
| 11 | `cancellation_fee_eur` | DecimalField | Storno <24h = Ausfallpauschale (SC9) |
| 12 | `external_invoice_id` | CharField | After ZAD export, what external ID? (UC-10) |
| 13 | `billing_exported_at` | DatetimeField | When was this trip last exported? (UC-10) |
| 14 | `wait_time_minutes` | IntField | Driver waited X minutes at pickup — billable? (CS4) |
| 15 | `modified_at` | DatetimeField | When was this trip last modified? (UC-9) |
| 16 | `version` | IntField | Optimistic locking for modifications (UC-9) |
| 17 | `escalation_status` | CharField | 'offen', 'in_bearbeitung', 'geloest' (UC-7) |
| 18 | `vehicle_type_override` | CharField | Override Patient's default vehicle_type (UB3) |
| 19 | `overrides_template` | BooleanField | If trip from recurring template was manually edited (UB6) |

### 5.4 Critical Type Issues

#### 5.4.1 Naive Datetime (P1 — DATA CORRUPTION RISK)

```python
scheduled_pickup = fields.DatetimeField()  # NAIVE — no tzinfo
```

**Impact:** On Sommerzeit-Umstellung (March: 02:00→03:00, October: 03:00→02:00), trips scheduled during the ambiguous hour are indistinguishable. Two different trips at "02:30" on October 25, 2026 are actually 1 hour apart but stored identically. This is a **data integrity bug**, not a display issue.

**Fix:** Store as UTC with explicit conversion at I/O boundary. Tortoise ORM supports `timezone-aware` via the underlying DB driver. SQLite stores datetimes as ISO-8601 strings — naive dates drop the offset. Solution: always serialize with timezone.

#### 5.4.2 Float for Money (P2 — Rounding Errors)

```python
fare_eur = fields.FloatField(null=True)
```

**Impact:** Summing 1000 trips at €12.50 each: `1000 * 12.50 = 12500.0` in float is actually `12499.999999999998` due to IEEE 754 binary representation. Over months of billing, discrepancy grows.

**Fix:** `fields.DecimalField(max_digits=8, decimal_places=2)` or `fields.IntField()` (store cents). Recommendation: DecimalField (design decision D6).

---

## 6. TripEvent — Gap Analysis (CRITICALLY INCOMPLETE)

### 6.1 Fields Present vs. Required

| Field | Type | Status | Gap |
|-------|------|--------|-----|
| `trip` | FK → Trip | ✅ | — |
| `event_type` | CharField(50) | ⚠️ P2 | No CHECK constraint for valid types |
| `message` | TextField, nullable | ✅ | — |
| `created_at` | DatetimeField, auto_now_add | ✅ | — |

### 6.2 Missing Fields (P1 — Haftungsrelevant)

| Field | Priority | Rationale |
|-------|----------|-----------|
| **`triggered_by`** (who triggered this event?) | P1 | driver_id, patient_id, system. UC-6: "Fahrer hat Patient angeblich um 8:15 aufgenommen" — without this, no legal audit trail |
| **`metadata`** (JSON) | P1 | UC-7: escalation needs context (which driver declined? Why?). UC-9: modification needs old/new values |

### 6.3 Missing Event Types (Not in Schema but Used in Requirements)

Current code mentions: `status_change`, `problem`, `note`, `system`

Required by edge cases:
| Event Type | Priority | Scenario |
|-----------|----------|----------|
| `cancellation` | P1 | SC2: who cancelled, why, when |
| `modification` | P1 | UB1-UB2: what changed, old/new values |
| `incident` | P2 | CS7: driver went to wrong address |
| `driver_switch` | P1 | UB4: driver change mid-trip |
| `no_show` | P2 | CS3: patient didn't show up |
| `escalation` | P1 | UC-7: escalation created/resolved |
| `assignment` | P2 | Driver assigned/removed |

---

## 7. Missing Tables (from Requirements §5.1)

| Table | Priority | Key Fields | Blocks |
|-------|----------|------------|--------|
| **Address** (embedded or table) | P1 | street, postal_code, city, lat, lon, google_place_id | Geocoding, OSRM, Muster-4 |
| **DriverAbsence** | P1 | driver_id (FK), start, end, reason (vacation/sick/training) | Dispatch — sick drivers get trips |
| **TripGroup** | P1 | id, vehicle_id, driver_id, scheduled_start, status | Sammelfahrt — completely unmodellable currently |
| **TripGroupMember** | P1 | trip_group_id (FK), trip_id (FK), stop_order | n:m Trip ↔ TripGroup |
| **TransportDocument** | P1 | trip_id (FK), document_type (muster4/bg/private), file_path, external_id | Legal compliance — §302 SGB V |
| **InsuranceApproval** | P1 | trip_id (FK), status (pending/approved/rejected), reference_number, valid_until | Kassengenehmigung |
| **InsuranceProvider** | P2 | name, ik_number, billing_portal | Referenztabelle für KK-Namen |
| **RecurringTripException** | P2 | recurring_trip_id (FK), date, reason | Feiertage, Praxisurlaub |
| **AuditLog** (generic) | P2 | table_name, row_id, action (CRUD), changed_by, old_values (JSON), new_values (JSON) | DSGVO compliance |

---

## 8. Index Analysis

### 8.1 Current State

**Zero explicit indices** in the schema. Only implicit indices exist:
- Primary keys (auto-indexed by Tortoise/SQLite)
- `Patient.telegram_id` (unique constraint → auto-index)
- `Driver.telegram_id` (unique constraint → auto-index)
- `Vehicle.license_plate` (unique constraint → auto-index)
- Foreign keys (SQLite does NOT auto-index FKs — unlike PostgreSQL)

**This means every FK join currently does a full table scan on SQLite.**

### 8.2 Query Patterns → Index Recommendations

Based on REQUIREMENTS_EDGE_CASES.md §4.2 and code inspection:

| # | Query Pattern | Frequency | Recommended Index | Rationale |
|---|--------------|-----------|-------------------|-----------|
| Q1 | All active trips for a driver today | **Very High** (every status change) | `(driver_id, status, scheduled_pickup)` | Composite: fast lookup by driver + status + time |
| Q2 | All trips for a patient (history) | Medium | `(patient_id, created_at)` | Patient asks "my trips" — sorted by recency |
| Q3 | Open trips for dispatch (geplant, no driver) | **Very High** (dispatch loop) | `(status, scheduled_pickup)` WHERE driver IS NULL | Core dispatch query — must be fast |
| Q4 | Driver availability in time window | **Very High** (dispatch) | `(driver_id, scheduled_pickup, scheduled_dropoff)` | Overlap detection (TODO in dispatch.py:106) |
| Q5 | Recurring trips needing generation | Medium (daily cron) | `(active_until, last_generated)` | Generator picks up where it left off |
| Q6 | Billing export in date range | Medium (monthly) | `(billing_status, scheduled_pickup)` | Monthly CSV export |
| Q7 | All active drivers | High (dispatch) | `(active, work_days)` | Driver roster — but work_days is a comma-string, can't index effectively |
| Q8 | Vehicle availability | Medium | `(vehicle_id, status)` JOIN trips | Which vehicles are in use? |

### 8.3 Recommended Indexes (SQL)

```sql
-- P1: Core dispatch + status queries (must exist before production)
CREATE INDEX idx_trips_driver_status_time ON trips(driver_id, status, scheduled_pickup);
CREATE INDEX idx_trips_status_pickup ON trips(status, scheduled_pickup) WHERE driver_id IS NULL;
CREATE INDEX idx_trips_patient_created ON trips(patient_id, created_at);

-- P1: Time window overlap detection
CREATE INDEX idx_trips_driver_pickup_dropoff ON trips(driver_id, scheduled_pickup, scheduled_dropoff);

-- P2: Billing and maintenance
CREATE INDEX idx_trips_billing_pickup ON trips(billing_status, scheduled_pickup);
CREATE INDEX idx_recurring_active_lastgen ON recurring_trips(active_until, last_generated);
CREATE INDEX idx_trips_vehicle_status ON trips(vehicle_id, status);

-- P2: Foreign keys (SQLite doesn't auto-index FKs)
CREATE INDEX idx_trips_recurring_template ON trips(recurring_template_id);
CREATE INDEX idx_tripevents_trip ON trip_events(trip_id);
```

### 8.4 Index Trade-offs

| Concern | Mitigation |
|---------|------------|
| Write overhead on `trips` (5+ indexes) | Trips are write-light (created once, status-updated ~8 times). Acceptable. |
| SQLite partial index support | `WHERE driver_id IS NULL` is valid SQLite syntax (3.8.0+). Works. |
| Composite index order matters | `(status, scheduled_pickup)` — status first for equality filter, time for range scan. Correct. |
| `work_days` as comma-string | Cannot index. Must normalize to separate DriverWorkDay table or JSON array for Q7. |

### 8.5 Tortoise ORM Index Declaration

```python
class Trip(Model):
    # ...
    class Meta:
        table = "trips"
        indexes = [
            ("driver_id", "status", "scheduled_pickup"),
            ("status", "scheduled_pickup"),
            ("patient_id", "created_at"),
            ("driver_id", "scheduled_pickup", "scheduled_dropoff"),
            ("billing_status", "scheduled_pickup"),
            ("vehicle_id", "status"),
        ]
```

**Note:** Tortoise ORM's `indexes` in Meta creates CREATE INDEX statements during `generate_schemas()`. SQLite partial indexes (WHERE clause) may not be supported — verify. If not, use raw SQL migration.

---

## 9. Edge Case Coverage Matrix

### 9.1 Storno (10 scenarios from §3.1)

| Scenario | Currently Possible? | Missing Fields |
|----------|-------------------|----------------|
| SC1: Patient cancels before assignment | ✅ (set `status=storniert`) | `cancelled_by`, `cancelled_at` |
| SC2: Patient cancels after assignment | ⚠️ (status change works, no driver notification) | `cancelled_by`, `cancelled_at`, `TripEvent.triggered_by` |
| SC3: Cancel while driver en route | ❌ | `cancellation_fee_eur`, all SC1 fields |
| SC4: Driver cancels (sick) | ❌ | `cancelled_by=driver`, re-dispatch needs DriverAbsence |
| SC5: Driver no-show timeout | ❌ | `status_changed_at` for timeout detection |
| SC6: Chef cancels (force majeure) | ⚠️ | `cancelled_by=chef`, `cancellation_reason` |
| SC7: Cancel return trip only | ❌ | `return_trip_id` FK — can't link trips |
| SC8: Cancel recurring instance | ❌ | RecurringTripException table |
| SC9: Late cancel fee | ❌ | `cancellation_fee_eur`, business logic |
| SC10: Mass cancellation | ❌ | API design issue, not schema |

**Coverage: 1/10 fully possible, 2/10 partial, 7/10 impossible.**

### 9.2 Umbuchung (7 scenarios from §3.2)

| Scenario | Currently Possible? | Missing Fields |
|----------|-------------------|----------------|
| UB1: Time change | ⚠️ (can edit, no audit) | `TripEvent.metadata` (JSON), `modified_at`, `version` |
| UB2: Destination change | ⚠️ (same) | Same as UB1 |
| UB3: Vehicle type change | ⚠️ | `vehicle_type_override` on Trip |
| UB4: Driver switch mid-trip | ⚠️ (can reassign FK, no audit) | `TripEvent` with `event_type=driver_switch`, `triggered_by` |
| UB5: Recurring template change | ❌ | RecurringTripException + batch update logic |
| UB6: Single instance override | ❌ | `Trip.overrides_template` |
| UB7: Patient address change propagates | ❌ | Address model + propagation logic |

**Coverage: 0/7 fully possible, 4/7 partial, 3/7 impossible.**

### 9.3 Billing (5 scenarios from §3.3)

| Scenario | Currently Possible? | Missing Fields |
|----------|-------------------|----------------|
| TR1: Driver late, patient takes taxi | ❌ | `cancellation_reason="driver_late"` |
| TR2: Wrong vehicle type | ⚠️ | `billing_status=disputed`, no field for dispute reason |
| TR3: Patient exits mid-trip | ❌ | Status 'aborted' missing from TRIP_STATES, `distance_km` for partial billing |
| TR4: Insurance rejects claim | ❌ | `InsuranceApproval` table |
| TR5: Km reimbursement (private) | N/A | Out of scope |

**Coverage: 0/4 fully possible, 1/4 partial.**

### 9.4 Complex Scheduling (7 scenarios from §3.4)

| Scenario | Currently Possible? | Missing Fields |
|----------|-------------------|----------------|
| CS1: DST transition | 🔴 **BUG** | Naive datetime — data corruption |
| CS2: Holidays vary by state | ❌ | `RecurringTrip.skip_on_holidays` + `holiday_state` |
| CS3: No-show patient | ❌ | Status 'no_show' needs adding to TRIP_STATES |
| CS4: Excessive wait time | ❌ | `wait_time_minutes` |
| CS5: Double-booking detection | ❌ | Overlap query needs index Q4 — not even implemented |
| CS6: Shift end overlap | ❌ | Design decision needed: allow start in hours, end beyond? |
| CS7: Wrong destination | ⚠️ | `TripEvent` for incident — needs `triggered_by` + `metadata` |

**Coverage: 0/7 fully possible, 1/7 partial, 6/7 impossible (including 1 data corruption bug).**

---

## 10. Critical Bugs Found

### 10.1 Naive Datetime (CS1 — Data Corruption)

**File:** schema.py:102  
**Line:** `scheduled_pickup = fields.DatetimeField()`  
**Severity:** Critical — data integrity  
**Impact:** Ambiguous timestamps during DST transitions. Two distinct real-world times stored as identical DB values.

### 10.2 Locale-Dependent Day Matching (dispatch.py:103)

**File:** core/dispatch.py:103  
**Line:** `day_name = trip.scheduled_pickup.strftime("%a")[:2]`  
**Severity:** High — breaks on non-German locales  
**Impact:** On English-locale servers, `strftime("%a")` returns "Thu" not "Do" → `[:2]` gives "Th" → never matches "Do" in `work_days` → drivers who work Thursdays are never dispatched.

### 10.3 Float for Money (schema.py:115)

**File:** schema.py:115  
**Line:** `fare_eur = fields.FloatField(null=True)`  
**Severity:** Medium — accumulates over time  
**Impact:** Summing fares produces rounding errors. Over 1000+ trips, discrepancy grows.

### 10.4 No Overlap Detection (dispatch.py:106)

**File:** core/dispatch.py:106  
**Line:** `# TODO: Check for overlapping trips (query DB)`  
**Severity:** High — double-booking  
**Impact:** Driver can be assigned to overlapping trips. No guard exists.

---

## 11. State Machine Gaps

Current TRIP_STATES: geplant → zugewiesen → anfahrt → angekommen → patient_an_bord → unterwegs → abgesetzt → abgeschlossen (+ storniert, problem)

**Missing states from edge cases:**
| State | Scenario | Priority |
|-------|----------|----------|
| `no_show` | CS3: Patient doesn't appear | P2 |
| `aborted` | TR3: Patient exits mid-trip | P2 |
| `disputed` | TR2: Billing dispute | P2 |

**Missing transitions:**
| Transition | Scenario | Priority |
|-----------|----------|----------|
| `stornieren` from `abgesetzt` | SC3: Cancel after dropoff? Edge case | P3 |
| `problem_melden` from `geplant` | Driver reports issue before assignment | P3 |
| `reopen` from `abgeschlossen` | Billing correction | P2 |

---

## 12. Migration Path (SQLite-Safe)

SQLite has no `ALTER TABLE ADD COLUMN ... NOT NULL DEFAULT ...` with transactional integrity. Migration strategy:

### Phase 0: Add nullable P1 fields (no data loss)
```sql
ALTER TABLE trips ADD COLUMN ride_type VARCHAR(20);
ALTER TABLE trips ADD COLUMN return_trip_id INTEGER REFERENCES trips(id);
ALTER TABLE trips ADD COLUMN cancelled_by VARCHAR(20);
ALTER TABLE trips ADD COLUMN cancelled_at TIMESTAMP;
ALTER TABLE trips ADD COLUMN cancellation_reason TEXT;
ALTER TABLE trips ADD COLUMN distance_km REAL;
ALTER TABLE trips ADD COLUMN billing_code VARCHAR(20);
ALTER TABLE trips ADD COLUMN booking_channel VARCHAR(20);
ALTER TABLE trips ADD COLUMN status_changed_at TIMESTAMP;

ALTER TABLE trip_events ADD COLUMN triggered_by VARCHAR(50);
ALTER TABLE trip_events ADD COLUMN metadata TEXT;  -- JSON

ALTER TABLE patients ADD COLUMN street VARCHAR(200);
ALTER TABLE patients ADD COLUMN postal_code VARCHAR(10);
ALTER TABLE patients ADD COLUMN city VARCHAR(100);
ALTER TABLE patients ADD COLUMN lat REAL;
ALTER TABLE patients ADD COLUMN lon REAL;
ALTER TABLE patients ADD COLUMN data_retention_until DATE;
ALTER TABLE patients ADD COLUMN deletion_requested_at TIMESTAMP;

ALTER TABLE recurring_trips ADD COLUMN last_generated TIMESTAMP;

ALTER TABLE drivers ADD COLUMN driver_license_number VARCHAR(50);
```

### Phase 1: Create new tables (no migration risk)
```sql
CREATE TABLE driver_absences (...);
CREATE TABLE trip_groups (...);
CREATE TABLE trip_group_members (...);
CREATE TABLE transport_documents (...);
CREATE TABLE insurance_approvals (...);
CREATE TABLE insurance_providers (...);
```

### Phase 2: Backfill and add constraints
- Migrate existing TextField addresses to structured fields
- Add CHECK constraints on enums
- Add NOT NULL where data allows

---

## 13. Summary & Recommendations

### Immediate Actions (P1 — Can't Go Live Without)

1. **Add 7 fields to Trip** (ride_type, return_trip_id, cancelled_by, cancelled_at, cancellation_reason, distance_km, billing_code)
2. **Add 2 fields to TripEvent** (triggered_by, metadata JSON)
3. **Add structured address fields to Patient** (street, postal_code, city, lat, lon)
4. **Add DSGVO fields to Patient** (data_retention_until, deletion_requested_at)
5. **Create DriverAbsence table**
6. **Create TripGroup + TripGroupMember tables**
7. **Create TransportDocument table**
8. **Create InsuranceApproval table**
9. **Add `last_generated` to RecurringTrip**
10. **Add `driver_license_number` to Driver**
11. **Fix timezone handling** — store all datetimes as UTC
12. **Add 4 P1 indexes** (see §8.3)

### Short-term (P2 — Before Scaling)

1. Add 9 P2 Trip fields (cancellation_fee_eur, version, escalation_status, etc.)
2. Add structured special needs to Patient
3. Add vehicle maintenance fields (tuev_until, active flag)
4. Create InsuranceProvider, RecurringTripException, AuditLog tables
5. Fix Float → Decimal for fare_eur
6. Normalize work_days (comma-string → array or table)
7. Add DB-level CHECK constraints
8. Add P2 indexes

### Design Decisions Resolved by This Analysis

| Decision | Analysis Conclusion |
|----------|-------------------|
| D1: Round-trip model | Two linked trips with `return_trip_id` FK — clean for billing |
| D4: Address strategy | Embedded fields on Patient/Trip for MVP, migrate to Address table later |
| D5: Timezone strategy | Store UTC, convert at app boundary |
| D6: Money type | `DecimalField(max_digits=8, decimal_places=2)` |

---

*End of validation. Next steps: implement schema changes (backend-eng), create migration scripts, add indexes per §8.3.*
