# Krankenfahrt — Root Cause Analysis

## Scope: Database sharing, Chef dashboard trip visibility, Auto-dispatch silent failure

---

## FINDING 1 — CRITICAL: `_try_auto_dispatch` catches `DispatchError` and swallows it silently
**File:** `src/krankenfahrt/bots/patient_bot.py`  
**Lines:** 1023–1072 (`_try_auto_dispatch`), 1188–1191 (caller)

### The Bug
When a patient books a trip:
1. `_handle_book_intent` creates the trip (line 1117) ✓
2. Then calls `_try_auto_dispatch(trip, update)` (line 1189)
3. `_try_auto_dispatch` calls `engine.find_best_driver(trip, drivers)` (line 1034)
4. `find_best_driver` **RAISES** `DispatchError` when no driver matches all constraints (dispatch.py:225)
5. `_try_auto_dispatch` has **no try/except** — the exception propagates up
6. The caller wraps it in a generic `except Exception` (line 1189) that just logs a warning

### Impact
- The patient gets a success message ("✅ Fahrt gebucht!") but is NEVER told that no driver was found
- The chef is NEVER notified about the unassigned trip
- The trip exists in the DB with `status="geplant"` — someone has to manually check
- The log warning is easily missed in production

### Dead code
Line 1036 (`if assignment.driver is None:`) is **dead code** — `find_best_driver` never returns None, it raises.

### Fix needed
- Catch `DispatchError` explicitly in `_try_auto_dispatch` or its caller
- Send an escalation message to the chef when auto-dispatch fails
- Notify the patient that a driver will be assigned shortly

---

## FINDING 2 — CRITICAL: Driver vehicle check blocks ALL newly created drivers
**File:** `src/krankenfahrt/core/dispatch.py`  
**Lines:** 243–267 (`_check_vehicle_match`)

### The Bug
`_check_vehicle_match` requires EVERY driver to have a `vehicle` FK set:

```python
if driver.vehicle is None:
    violations.append(ConstraintViolation(
        ConstraintKind.VEHICLE_TYPE_MISMATCH, driver.id,
        f"Driver has no vehicle assigned ..."
    ))
    return
```

When the chef creates a driver via `/fahrer add` in `chef_bot.py` (line 430–492), **no vehicle is assigned** — the `vehicle` FK defaults to `None`. Without an explicit `/fahrzeug` + linking step, every driver is immediately rejected by auto-dispatch.

### Impact
- **"No active drivers" message** despite drivers being registered and active
- The auto-dispatch constraint violation is swallowed (see Finding 1)
- The chef sees drivers in `/fahrer list` but auto-dispatch never matches them

### Root cause of driver/vehicle separation
The chef must:
1. Create a vehicle with `/fahrzeug add` (chef_bot.py:768)
2. ... link it to the driver (there's NO command for this!)
   
There is **no chef-bot command** to assign a vehicle to a driver. So even with vehicles created, drivers can't be linked.

### Fix needed
- Option A: Make vehicle nullable/optional in `_check_vehicle_match` (skip check if no vehicle)
- Option B: Add `/fahrer update <id> vehicle <vehicle_id>` command to chef_bot
- Option C: Auto-create a default vehicle for each driver on creation

---

## FINDING 3 — AutoDispatchHandler is defined but NEVER wired into production
**File:** `src/krankenfahrt/core/auto_dispatch.py` (line 79)  
**Evidence:** `AutoDispatchHandler` is only imported in test files (`tests/test_auto_dispatch.py`, `tests/integration/test_auto_dispatch.py`). Zero references in `src/krankenfahrt/bots/`.

### The Bug
There are **two separate auto-dispatch implementations**:
1. `AutoDispatchHandler` in `auto_dispatch.py` — well-designed with DI, proper escalation, NotificationSender abstraction. **UNUSED.**
2. Inline `_try_auto_dispatch` in `patient_bot.py` — ad-hoc, bare-minimum, broken.

The `AutoDispatchHandler` has proper escalation logic (lines 222–243) that notifies the chef when no driver is found. This code path never executes.

---

## FINDING 4 — Inconsistent datetime handling (naive vs aware)
**Files:**
- `src/krankenfahrt/bots/patient_bot.py` line 1103 — `dt.fromisoformat(...)` creates **naive** datetime
- `src/krankenfahrt/bots/chef_bot.py` line 1190 — `datetime.now()` creates **naive** local-time datetime
- `src/krankenfahrt/bots/driver_bot.py` line 38 — `datetime.now(UTC)` creates **aware UTC** datetime
- `src/krankenfahrt/models/schema.py` line 108 — `scheduled_pickup` stores whichever it receives

### Potential issue
Trip `scheduled_pickup` values are naive (created by patient_bot). Chef dashboard filter values are also naive. So string comparison works correctly for date-range filtering.

**However**, if the server is in UTC but the user operates in Europe/Berlin timezone:
- `datetime.now()` returns UTC on the server
- Trip `scheduled_pickup` is naive but semantically "local time"
- Dashboard `day_start` is UTC midnight
- If UTC midnight = 02:00 CEST, and the trip is at 08:00 CEST = 06:00 UTC
- The range `[00:00 UTC, 23:59 UTC]` correctly includes 06:00 UTC

So this is **not the primary cause** of the dashboard issue, but it is a latent bug that will break when:
- Trips span UTC date boundaries (e.g., trip at 01:00 CEST = 23:00 UTC previous day)
- The server TZ differs from the user's expectation

### Fix needed
- Use timezone-aware datetimes everywhere (preferably UTC)
- Store all timestamps as UTC in the database
- Convert to local time only for display purposes

---

## FINDING 5 — Tortoise ORM DOES enable WAL mode (NOT a bug)
**File:** `venv/lib/python3.12/site-packages/tortoise/backends/sqlite/client.py`  
**Lines:** 74–76

```python
self.pragmas.setdefault("journal_mode", "WAL")
self.pragmas.setdefault("journal_size_limit", 16384)
self.pragmas.setdefault("foreign_keys", "ON")
```

Tortoise ORM automatically enables WAL mode and foreign keys for all SQLite connections. This is correct and prevents the "database is locked" errors. **No action needed.**

---

## FINDING 6 — Single database connection shared by all bots (NOT a bug)
**File:** `venv/lib/python3.12/site-packages/tortoise/backends/sqlite/client.py`  
**Lines:** 78–79, 81–94

```python
self._connection: aiosqlite.Connection | None = None
self._lock = asyncio.Lock()
```

Tortoise SQLite client uses a **single aiosqlite connection** behind an `asyncio.Lock()`. Since `main.py` calls `Tortoise.init()` once before starting all three bots, every bot handler shares the exact same connection. Serialized access via the lock guarantees consistency. **No action needed.**

---

## FINDING 7 — DATABASE_URL resolution (correct on Railway, but fragile locally)
**File:** `src/krankenfahrt/config.py` lines 18–22  
**File:** `Dockerfile` line 21

### Current behavior
- **Docker/Railway:** `DATABASE_URL=sqlite:///cache/krankenfahrt.db` (set in Dockerfile env, overridable by Railway env var)
- **Local dev:** Defaults to `sqlite://{PROJECT_ROOT}/data/krankenfahrt.db` → `/Users/.../krankenfahrt/data/krankenfahrt.db`

### Potential issue
If `DATABASE_URL` env var is not set on Railway and the Dockerfile line is overridden, the application falls back to `sqlite://PROJECT_ROOT/data/krankenfahrt.db` where PROJECT_ROOT = `/app` (inside container). This is NOT on the persistent volume, so data is lost on restart. But this still wouldn't cause different bots to access different databases — they all share the same connection.

**No bug in production assuming Railway volume is mounted at `/cache`.**

---

## FINDING 8 — Chef dashboard `prefetch_related` may mask join failures
**File:** `src/krankenfahrt/bots/chef_bot.py` lines 1194–1197

```python
return await (
    Trip.filter(scheduled_pickup__gte=day_start, scheduled_pickup__lte=day_end)
    .prefetch_related("patient", "driver")
    .all()
)
```

If a Trip has a `patient_id` that doesn't correspond to an existing Patient record (due to data corruption or partial migration), `prefetch_related` would raise an error that propagates up to the `try/except` in `cmd_dashboard` (line 1241). The chef would see "❌ Fehler beim Laden der Fahrten" instead of the dashboard. This is a secondary concern but possible with manual DB manipulation.

---

## SUMMARY: Root Causes for the Three Reported Problems

### Problem 1: "Bots don't share the same database"
**VERDICT: NOT CONFIRMED.** All bots run in one asyncio process (`main.py` line 212–289). Tortoise ORM is initialized once (line 148–152) with a single aiosqlite connection behind a lock. All three bots unquestionably share the same SQLite database.

**If the user still observes data isolation**, the cause is likely one of:
- Different Railway service instances writing to different volumes because the persistent volume is not shared or mounted correctly
- A deployment race where an old container writes to one DB and a new container reads from another

### Problem 2: "Auto-dispatch says 'no active drivers'"
**VERDICT: CONFIRMED — two root causes.**

| Cause | File | Line |
|-------|------|------|
| **RC1:** Driver vehicle check blocks ALL drivers without a vehicle FK | `dispatch.py` | 250–258 |
| **RC2:** `DispatchError` is silently swallowed; no notification to patient or chef | `patient_bot.py` | 1034–1036, 1189–1191 |
| **RC3:** `AutoDispatchHandler` (has proper escalation) is never wired up | `auto_dispatch.py` | 79 (defined, never imported) |

**Flow of failure:**
1. Patient books trip → trip created ✓
2. `_try_auto_dispatch` queries active drivers → finds them ✓
3. `find_best_driver` checks each driver → ALL fail `_check_vehicle_match` (no vehicle → ConstraintViolation)
4. `find_best_driver` raises `DispatchError` with violations=[VEHICLE_TYPE_MISMATCH]
5. Exception propagates up, caught by blanket `except Exception` at line 1189
6. Logged as warning, **no one is told**, trip stays "geplant" forever

### Problem 3: "Chef dashboard doesn't show the trip"
**VERDICT: CONFIRMED — indirect cause.** The trip IS in the database (created at line 1117). The dashboard query (line 1194) should find it if `scheduled_pickup` falls within today's date range. If the trip was created for a different day than the one the chef queries, it correctly doesn't appear (this is expected behavior).

**If the trip is for TODAY and still doesn't appear**, possible causes:
1. **The trip's `scheduled_pickup` has a different date than expected** (NLU parsing error, wrong date extraction)
2. **Data was written to a different database file** (see Problem 1 — unlikely but possible in multi-service deployments)
3. **`prefetch_related` raises an exception** due to missing related records (edge case)

---

## RECOMMENDED FIXES (Priority Order)

### P1 — Fix auto-dispatch escalation chain
Edit `src/krankenfahrt/bots/patient_bot.py`:
- In `_try_auto_dispatch`, catch `DispatchError` explicitly and send chef notification
- Wire up `AutoDispatchHandler` from `auto_dispatch.py` instead of using inline code
- Remove dead code on line 1036

### P2 — Fix driver-vehicle constraint
Edit `src/krankenfahrt/core/dispatch.py`:
- Make vehicle match check optional when `driver.vehicle` is None (skip or warn)
- OR add vehicle assignment command to chef bot (`/fahrer update <id> vehicle <vid>`)

### P3 — Enforce timezone-aware datetimes
Edit all bot files to use `datetime.now(timezone.utc)` consistently, convert to local time only for display.
