# Krankenfahrt Bot Feature Analysis

## Legend
| Status | Meaning |
|--------|---------|
| ✅ | Fully implemented |
| ⚠️ | Partially implemented / MVP quality |
| 🔜 | Planned / stubbed / not yet wired |

---

# 1. Patient-Bot (@FahrGast)

**Role:** Patient self-service interface for booking rides and managing profile/templates.
**Auth:** Patients access only their own data; admins (ADMIN_TELEGRAM_IDS) can override via `/profil_as`.

| # | Feature | Trigger | Beschreibung | What it reads | What it writes | Status |
|---|---------|---------|-------------|---------------|---------------|--------|
| 1 | **Auto-Registration & Welcome** | `/start` — Command | On first visit: creates Patient record with defaults (name from Telegram, pickup="(bitte ergänzen)") and shows welcome + command list. On return visit: shows profile summary. | Telegram user info (name, id) | `Patient` record (create if new) | ✅ |
| 2 | **Profile View** | `/profil` — Command | Shows the patient's stored profile (name, phone, addresses, insurance, vehicle type, special needs, notes) as formatted Markdown. | `Patient` by telegram_id | — (read-only) | ✅ |
| 3 | **Profile Edit (Multi-Step)** | `/profil_edit` — Command → Conversation | Walks through 9 steps: Name → Phone → Pickup Address → Dest Address → Insurance Provider → Insurance Number → Vehicle Type → Special Needs → Notes. Each step accepts text or `/skip`. Persists all changes at the end. | `Patient` (initial load) | `Patient` (all fields updated) | ✅ |
| 4 | **Admin Profile Override** | `/profil_as <telegram_id>` — Command (admin-only in code, handler not shown in register_handlers) | Allows admin to view another patient's profile by their Telegram ID. | `Patient` by admin_viewing_id | — (read-only) | ⚠️ (mentioned in docstring, but handler not registered) |
| 5 | **Template List** | `/vorlagen` — Command | Lists all recurring trip templates for the patient with status emoji and summary. | `RecurringTrip` filtered by patient | — (read-only) | ✅ |
| 6 | **Template Detail** | `/vorlage_show <id>` — Command | Shows a single template's full details (pickup, dest, days, times, vehicle type, expiry). | `RecurringTrip` by id | — (read-only) | ✅ |
| 7 | **Template Create (Multi-Step)** | `/vorlage_neu` — Command → Conversation | Walks through 7 steps: Pickup → Dest → Days → Pickup Time → Return Time → Vehicle Type → Confirmation. Pre-fills from patient defaults. Creates `RecurringTrip` record on confirm. | `Patient` (defaults), `RecurringTrip` (check) | `RecurringTrip` (create) | ✅ |
| 8 | **Template Edit (Multi-Step)** | `/vorlage_edit <id>` — Command → Conversation | User selects field to edit via inline buttons (pickup, dest, days, times, vehicle type), then enters new value. Persists to DB. | `RecurringTrip` by id | `RecurringTrip` (selected field) | ✅ |
| 9 | **Template Delete** | `/vorlage_del <id>` — Command → Button confirmation | Shows template detail with "✅ Ja, löschen" / "❌ Abbrechen" inline buttons. Deletes on confirm. | `RecurringTrip` by id | `RecurringTrip` (delete) | ✅ |
| 10 | **NLU Booking (Free-Text)** | Natural language text — e.g. "Morgen 8 Uhr zur Dialyse Klinikum Nord" | All non-command text messages go through DeepSeek-based NLU (`extract_booking_intent`) to extract structured booking data. Confidence threshold: 0.40. | `Patient` (telegram_id), NLU result | — (routes to sub-handler) | ✅ |
| 11 | **Book Intent → Create Trip** | NLU `action=book` | Creates a `Trip` record (status="geplant"). If `return_time` present, creates a round-trip (second Trip). Sends confirmation. Calls auto-dispatch. | `Patient`, NLU `BookingIntent` | `Trip` (1 or 2 records), `TripEvent` | ✅ |
| 12 | **Info Intent → Upcoming Trips** | NLU `action=info` | Shows the patient's next 5 upcoming trips with status icons and times. | `Trip` filtered by patient + future date | — (read-only) | ✅ |
| 13 | **Recurring/Cancel/Change Intents** | NLU `action=recurring|cancel|change` | Shows "not yet available" message and redirects to support/commands. | — | — (informational) | ⚠️ (stubbed, not implemented) |
| 14 | **Low Confidence / Rephrase** | NLU confidence < 0.40 | Asks the patient to rephrase with example phrases. | NLU confidence | — | ✅ |
| 15 | **Unregistered Patient Handling** | NLU handler — no Patient found | Tells user to use `/start` to register first. | `Patient` lookup | — | ✅ |
| 16 | **Auto-Dispatch on Booking** | After successful Trip creation | Calls `GreedyDispatchEngine.find_best_driver()`. If a driver is found: assigns driver, changes status to "zugewiesen", logs `TripEvent`, sends notification via Driver-Bot API. If no driver found: logs warning and notifies chef via Chef-Bot API (HTTP call). | `Driver` (active), `GreedyDispatchEngine` | `Trip` (driver_id, status), `TripEvent` | ✅ |
| 17 | **Push Status Update to Patient** | `push_status_update(app, chat_id, status)` — Called externally on state change | Sends a Markdown-formatted status notification to the patient's Telegram chat. Uses `STATUS_DISPLAY` map for German display text. Incorporates driver name, timestamps. | Trip status, chat_id | Telegram message (sent) | ✅ |
| 18 | **Live Location: Start** | `start_live_tracking(app, trip_id, chat_id, lat, lon, driver_name)` — Called when driver en route | Sends initial `send_location` with `live_period=3600s`. Stores session (chat_id, message_id) in `LiveLocationTracker`. Sends preceding text status with driver name. | `LiveLocationSession` | Telegram live location message | ✅ |
| 19 | **Live Location: Update** | `update_live_tracking(app, trip_id, lat, lon)` — Called periodically | Edits the existing location message via `edit_message_live_location` — Telegram UI shows moving blue dot. | `LiveLocationSession` (trip_id → message_id) | Telegram location edit | ✅ |
| 20 | **Live Location: Stop** | `stop_live_tracking(app, trip_id, chat_id, arrived=True)` — Called on arrival/completion | Calls `stop_message_live_location`. Optionally sends "angekommen" status notification. Removes session from tracker. | `LiveLocationSession` | Telegram location stop | ✅ |
| 21 | **State-Change Decision Helpers** | `should_start_live_location()`, `should_stop_live_location()`, `should_notify_patient()` — Pure functions | Determine which actions to take when a trip state changes. `_LOCATION_START_STATES = {"anfahrt"}`, `_LOCATION_STOP_STATES = {"angekommen", "abgesetzt", "abgeschlossen", "storniert"}`, `_NOTIFY_STATES = {"zugewiesen"..."problem"}` | Trip new_status string | Boolean decision | ✅ |

---

# 2. Driver-Bot (@FahrLenker)

**Role:** Order acceptance, status update buttons, voice control, shift management, NLU chat.
**Flow:** Driver receives order → inline keyboard advances through states (Annehmen → Angekommen → Abgeholt → Zugestellt → Abschließen).

| # | Feature | Trigger | Beschreibung | What it reads | What it writes | Status |
|---|---------|---------|-------------|---------------|---------------|--------|
| 1 | **Driver Registration Check** | `/start` — Command | Looks up `Driver` by telegram_id. If found: welcome back + command list. If not: tells user they're not registered and gives their Telegram ID to give to dispatcher. | `Driver` by telegram_id | — (read-only) | ✅ |
| 2 | **Today's Trip Overview** | `/heute` — Command | Shows driver's name, shift window (first pickup → last dropoff), trip count, each trip with emoji+time+status, and break summary (completed breaks + active break). | `Trip` (today's by driver_id), `DriverBreak` (today's) | — (read-only) | ✅ |
| 3 | **Break Toggle (Start/End)** | `/pause` — Command | If no active break: creates `DriverBreak` with start_time=now, replies "☕ Pause gestartet". If active break: sets end_time=now, computes duration, replies "✅ Pause beendet". | `DriverBreak` (active check by driver_id) | `DriverBreak` (create or update end_time) | ✅ |
| 4 | **Trip State Transition Keyboards** | Inline buttons: `trip:<trip_id>:<trigger>` — Callback | Builds inline keyboards with only valid next-state buttons (from `TRIGGER_MAP`). Each button advances the state machine. Button labels: "✅ Annehmen" (losfahren), "📍 Angekommen" (ankunft_melden), "👤 Abgeholt" (patient_aufnehmen), "🚗 Fahrt beginnt" (fahrt_beginnen), "✅ Zugestellt" (patient_absetzen), "🔒 Abschließen" (abschliessen), "⚠️ Problem" (problem_melden), "❌ Ablehnen" (stornieren), "🔄 Neu zuweisen" (fahrer_neu_zuweisen). | `TRIGGER_MAP` from state_machine.py, Trip state | `Trip` (status), `TripEvent` (status_change) | ✅ |
| 5 | **Trip State Transition Execution** | Button press → `handle_trip_callback()` | Decodes `trip:<id>:<trigger>`, loads Trip, verifies driver assignment, validates trigger allowed from current state, runs `TripStateMachine` transition, persists state to DB, logs `TripEvent`, updates message with new state+keyboard. Terminal states remove keyboard. | `Trip` (by id, with patient+driver), `TRIGGER_MAP` | `Trip` (status), `TripEvent` | ✅ |
| 6 | **Send Trip Notification to Driver** | `send_trip_to_driver(app, trip, driver)` — Called by dispatch/assignment flow | Formats trip info (patient name, time, addresses, vehicle, nav link) and sends as Telegram message with inline state-transition keyboard. | `Trip`, `Driver`, `Patient` | Telegram message to driver | ✅ |
| 7 | **Voice Message → Transcribe → Intent → Status Update** | Voice message — `filters.VOICE` | Full pipeline: (1) Look up driver, (2) Download OGG audio from Telegram, (3) Transcribe with faster-whisper (German, model="small"), (4) Extract driver intent via `extract_driver_intent` (DeepSeek → rule fallback), (5) If trip trigger: find active trip, validate trigger, execute state machine transition, (6) If pause action: start/end break. Responds with transcript + result. | Telegram voice file, `Driver` (by telegram_id), `Trip` (active for driver), `DriverBreak` | `Trip` (status), `TripEvent`, `DriverBreak` | ✅ |
| 8 | **Natural Language Chat (Driver)** | Free text (non-command) — `handle_natural_message()` | Sends text through DeepSeek via `generate_driver_response()`. The LLM receives driver's upcoming trips and formulates a conversational German response (1-3 sentences). Falls back to structured trip list if LLM fails. | `Driver` (by telegram_id), `Trip` (upcoming by driver_id) | — (read-only, responds in chat) | ✅ |

**Keyboard ↔ State Machine Mapping:**

| Button Label | Trigger | Source State(s) | Dest State |
|---|---|---|---|
| ✅ Annehmen | `losfahren` | zugewiesen → anfahrt |
| 📍 Angekommen | `ankunft_melden` | anfahrt → angekommen |
| 👤 Abgeholt | `patient_aufnehmen` | angekommen → patient_an_bord |
| 🚗 Fahrt beginnt | `fahrt_beginnen` | patient_an_bord → unterwegs |
| ✅ Zugestellt | `patient_absetzen` | unterwegs → abgesetzt |
| 🔒 Abschließen | `abschliessen` | abgesetzt → abgeschlossen |
| ⚠️ Problem | `problem_melden` | zugewiesen..abgesetzt → problem |
| ❌ Ablehnen | `stornieren` | geplant..unterwegs → storniert |
| 🔄 Neu zuweisen | `fahrer_neu_zuweisen` | zugewiesen..angekommen → geplant |

---

# 3. Chef-Bot (@FahrtenChef)

**Role:** Dispatcher/Owner cockpit — trip dashboard, driver & vehicle CRUD, billing export, escalation management.
**Auth:** All handlers guarded by `@_require_admin` (checks `ADMIN_TELEGRAM_IDS`).

| # | Feature | Trigger | Beschreibung | What it reads | What it writes | Status |
|---|---------|---------|-------------|---------------|---------------|--------|
| 1 | **Help / Command List** | `/start` — Command | Shows available commands: /dashboard, /export csv/pdf, /fahrer, /fahrzeug. | — | — | ✅ |
| 2 | **Daily Dashboard** | `/dashboard` — Command | Shows all today's trips with color-coded status (🔴 geplant, 🟡 zugewiesen, 🔵 anfahrt/angekommen/patient_an_bord/unterwegs, 🟠 abgesetzt, 🟢 abgeschlossen, ⚫ storniert, 🔴 problem). Each line: trip ID, time, patient, route, driver. Summary counts by status. | `Trip` (today's, with patient+driver), `Driver` (active) | — (read-only) | ✅ |
| 3 | **Manual Driver Assignment** | Inline button: `assign_<trip_id>_<driver_id>` — Callback | For trips in "geplant" status, shows inline buttons with active driver names. On click: assigns driver, updates trip status to "zugewiesen", refreshes dashboard. Validates trip and driver exist. | `Trip` (by id), `Driver` (by id, active) | `Trip` (driver_id, status) | ✅ |
| 4 | **CSV Billing Export** | `/export csv [von] [bis]` — Command | Generates UTF-8-BOM semicolon-delimited CSV with billing data (invoice number, date, patient, KK, addresses, fare, status). Optional date range filter. Sends as Telegram document. | `Trip` (with patient join), `ExportFilters` | CSV file on disk | ✅ |
| 5 | **PDF Invoice (Muster-4)** | `/export pdf <patient_id> [von] [bis]` — Command | Generates a DIN-compliant Muster-4 PDF invoice using ReportLab. Includes sender, recipient (KK), patient details, itemized trip table, net/VAT/gross summary, payment terms, bank details. Sends as Telegram document. | `Trip` (by patient_id, date filtered), `Patient` | PDF file on disk | ✅ |
| 6 | **Driver: Create** | `/fahrer add <Vorname> <Nachname> <Telefon> [Telegram-ID]` — Command | Creates a new `Driver` record with name, phone, optional telegram_id. Checks for name duplicates. Uses `db_retry` for resilience. | `Driver` (duplicate check) | `Driver` (create) | ✅ |
| 7 | **Driver: List** | `/fahrer list` / `/fahrer list-active` — Command | Lists all drivers or only active ones, with ID, name, phone, status, P-Schein, work hours/days. | `Driver` (all or active filter) | — (read-only) | ✅ |
| 8 | **Driver: Update** | `/fahrer update <ID> <field> <value>` — Command | Updates driver fields: name, phone, activate, deactivate, pschein (ja/nein). Validates ID and field. Uses `db_retry`. | `Driver` (by id) | `Driver` (updated field) | ✅ |
| 9 | **Driver: Delete (Soft)** | `/fahrer delete <ID> [confirm]` — Command | Requires two-step confirmation. Soft-deletes by setting `active=False` (preserves trip history). | `Driver` (by id) | `Driver` (active=False) | ✅ |
| 10 | **Vehicle: Create** | `/fahrzeug add <Marke> <Modell> <Kennzeichen> [Typ]` — Command | Creates a `Vehicle` record with make/model (stored in notes), license plate, vehicle type (Sitz default), capacity=1. Checks plate uniqueness. | `Vehicle` (duplicate check) | `Vehicle` (create) | ✅ |
| 11 | **Vehicle: List** | `/fahrzeug list` — Command | Lists all vehicles with ID, plate, type, capacity, notes. | `Vehicle` (all) | — (read-only) | ✅ |
| 12 | **Vehicle: Update** | `/fahrzeug update <ID> <field> <value>` — Command | Updates vehicle fields: type, plate, capacity, notes. Validates plate uniqueness. Uses `db_retry`. | `Vehicle` (by id) | `Vehicle` (updated field) | ✅ |
| 13 | **Vehicle: Delete (Hard)** | `/fahrzeug delete <ID> [confirm]` — Command | Requires two-step confirmation. Hard-deletes the vehicle record from DB. | `Vehicle` (by id) | `Vehicle` (delete) | ✅ |
| 14 | **Manual Escalation Trigger** | `/eskalieren <trip_id> [grund]` — Command | Creates an `Escalation` record with trigger_reason="manual". Presents inline keyboard with options: Neu zuweisen, Pausieren, Stornieren, Quittieren, Lösen. | `Trip` (by id, exists check), `Escalation` | `Escalation` (create) | ✅ |
| 15 | **List Open Escalations** | `/eskalationen` — Command | Shows all unresolved escalations with trip ID, patient name, trigger reason, status, creation time, detail. Each has an "Option wählen" button. | `Escalation` (open, with trip+patient) | — (read-only) | ✅ |
| 16 | **Escalation Audit Log** | `/eskalation_log [trip_id]` — Command | Queries escalation history (last 20 or filtered by trip). Shows ID, trip, trigger, status, chosen option, timestamps, resolution notes. | `Escalation` (all/by trip, with trip+patient) | — (read-only) | ✅ |
| 17 | **Escalation Option Processing** | Inline button: `esc_opt:<esc_id>:<option>` — Callback | Processes chef's choice: `reassign` → trip back to "geplant" + clear driver; `pause` → trip to "problem"; `cancel` → trip to "storniert"; `acknowledge` → escalation acknowledged; `resolve` → escalation resolved. Updates Escalation with option, resolver, timestamp. | `Escalation` (by id), `Trip` (by escalation.trip_id) | `Escalation` (status, chosen_option, resolved_by, timestamps), `Trip` (status) | ✅ |
| 18 | **Natural Language Chat (Chef)** | Free text (non-command) — `handle_natural_message()` | Sends text through DeepSeek via `generate_chef_response()`. The LLM receives today's trips and active drivers list, answers in German (2-3 sentences). Falls back to structured dashboard summary. | `Trip` (today's, with patient+driver), `Driver` (active) | — (read-only, responds in chat) | ✅ |

---

# 4. Cross-Cutting Services

## 4.1 NLU Service (`services/nlu.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **Chef Intent Classification** | `classify_chef(text)` → called from Chef NLU handler | Hybrid: keyword fast-path (9 pattern groups) → DeepSeek LLM fallback. Intents: dashboard, driver_add, driver_list, export, assign_trip, escalate, info, unknown. | Reads text; writes NluIntent | ✅ |
| 2 | **Driver Intent Classification** | `classify_driver(text)` → called from Driver NLU handler | Hybrid: keyword fast-path (5 pattern groups) → DeepSeek LLM fallback. Intents: heute, pause, ready, status, problem, info, unknown. | Reads text; writes NluIntent | ✅ |
| 3 | **Patient Intent Classification** | `classify_patient(text)` → via `extract_booking_intent` | Direct DeepSeek LLM classification (no keyword fallback in nlu.py; llm.py has its own). Intents: book, info, cancel, profile, recurring, unknown. | Reads text; writes NluIntent | ✅ |
| 4 | **Keyword Fallback** | `_keyword_match(text, patterns)` — Regex-based | Fast regex matching before LLM call for chef and driver. Returns first matching intent or None. Confidence=0.80 for keyword matches. | Reads text | ✅ |

## 4.2 Response Generation (`services/response_gen.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **Driver Conversational Response** | `generate_driver_response(text, telegram_id)` | Fetches driver's upcoming 10 trips, sends to DeepSeek with system prompt (friendly, du-form, German, 1-3 sentences). Falls back to structured list. | Reads `Driver`, `Trip` (upcoming, with patient) | ✅ |
| 2 | **Chef Conversational Response** | `generate_chef_response(text)` | Fetches today's all trips + active drivers, sends to DeepSeek (professional, German, 2-3 sentences, overview). Falls back to dashboard counts. | Reads `Trip` (today's, with patient+driver), `Driver` (active) | ✅ |

## 4.3 Voice Transcription (`services/voice.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **German Voice Transcription** | `transcribe_voice(audio_bytes, model_size="small")` | Uses local faster-whisper (CPU, int8, model="small" from cache dir). Writes bytes to temp .ogg, transcribes with beam_size=5, cleans up. Returns German text. | Reads audio bytes, cached Whisper model; writes transcript | ✅ |

## 4.4 Driver Intent Extraction (`services/driver_intent.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **LLM Driver Intent** | `extract_driver_intent(transcript, use_llm=True)` | Sends transcript to DeepSeek with system prompt + examples. Returns `DriverIntent` with action, trigger, confidence, params. | Reads transcript text; writes DriverIntent | ✅ |
| 2 | **Rule-Based Fallback** | `_rule_based_driver_intent(transcript)` | Regex pattern matching (8 action groups in priority order: stornieren > abschliessen > patient_absetzen > fahrt_beginnen > patient_aufnehmen > ankunft_melden > losfahren > problem_melden > pause). Confidence=0.80. | Reads transcript text; writes DriverIntent | ✅ |

## 4.5 Booking NLU (`services/llm.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **Booking Intent Extraction** | `extract_booking_intent(message)` | Uses DeepSeek with detailed system prompt (relative date resolution, time inference). Extracts action, pickup_date, pickup_time, return_time, dest, days, duration_min, reason, confidence. Uses `call_with_fallback` (retry + secondary provider) and rate limiter. | Reads text message; writes BookingIntent | ✅ |

## 4.6 State Machine (`core/state_machine.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **Trip State Machine** | `TripStateMachine(trip)` — wraps Trip model | 10 states (geplant → zugewiesen → anfahrt → angekommen → patient_an_bord → unterwegs → abgesetzt → abgeschlossen + storniert + problem) with 12 triggers. Uses `transitions` library. | Reads `trip.status`; writes `trip.status` (in-memory) | ✅ |
| 2 | **State Change Logging** | `on_enter_*/on_exit_*` callbacks | Every state change fires `StateChangeEvent` capturing trip_id, from→to, trigger, ISO timestamp, metadata. Events appended to in-memory log and forwarded to `event_logger`. | Reads trigger, state; writes `StateChangeEvent` | ✅ |
| 3 | **Problem Resolution** | `problem_loesen()` — Custom method | Restores the pre-problem state (saved in `_pre_problem_state` on entry to "problem"). Uses `Machine.set_state()` to bypass normal transitions. | Reads `_pre_problem_state` | ✅ |
| 4 | **Dynamic TRIGGER_MAP** | Computed from `TRIP_TRANSITIONS` | Maps each state to its valid triggers. Used by Driver-Bot for building keyboards without instantiating the machine. | Reads TRIP_TRANSITIONS | ✅ |
| 5 | **Guard Conditions** | `_guard_*` methods | `_guard_can_assign`: driver must be set; `_guard_can_complete`: must be in "abgesetzt"; `_guard_not_terminal`: no changes to terminal states. | Reads trip state | ✅ |

## 4.7 Auto Dispatch (`core/auto_dispatch.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **Auto-Dispatch Handler** | `AutoDispatchHandler.handle_new_trip(trip)` | Queries available drivers via injected callback, runs `GreedyDispatchEngine.find_best_driver()`, assigns best match (driver+vehicle, status→"zugewiesen"), sends driver notification via injected `NotificationSender`. If no match: escalates to chef. | Reads `Trip`, `Driver` (available); writes `Trip` (driver_id, status) | ✅ |
| 2 | **Escalation on No Match** | `_escalate()` | Sends formatted escalation message to chef with trip details and failure reason. | Reads trip data; writes via notifier | ✅ |

## 4.8 Dispatch Engine (`core/dispatch.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **Greedy Nearest-Driver Assignment** | `GreedyDispatchEngine.find_best_driver(trip, drivers)` | Scores each driver by Haversine distance (lower=better). Constraint gates: inactive skip, vehicle type match (soft), P-Schein (soft warning), work hours, work days, trip overlap (tolerance=5min). Raises `DispatchError` with all violations if no driver passes. | Reads `Driver` (position, schedule, constraints), `Trip` (position, time) | ✅ |
| 2 | **Haversine Distance** | `haversine_km(lat1, lon1, lat2, lon2)` | Great-circle distance in km. Clamps asin argument. Handles missing coordinates → returns 0.0. | Reads lat/lon pairs | ✅ |
| 3 | **Overlap Detection** | `_detect_overlap(driver, trip, tolerance=5min)` | Queries driver's active trips with overlapping time windows. Conflicting trip details returned. | Reads `Trip` (driver's active trips) | ✅ |

## 4.9 Escalation Management (`core/escalation.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **Create Escalation** | `create_escalation(trip_id, trigger_reason, trigger_detail)` | Creates Escalation with status="open". Validates reason (timeout/manual/system) and ESCALATION_ENABLED flag. Verifies trip exists. | Reads `Trip` (exists), config; writes `Escalation` | ✅ |
| 2 | **Process Escalation Option** | `process_escalation_option(esc_id, option, telegram_id, note)` | Validates option is valid and escalation not resolved. Updates Escalation: status, chosen_option, resolved_by, timestamps. Applies trip action: cancel→storniert, reassign→geplant+clear driver, pause→problem. | Reads `Escalation`, `Trip`; writes `Escalation` (status+meta), `Trip` (status) | ✅ |
| 3 | **List Open Escalations** | `get_open_escalations(limit=20)` | Returns newest-first unresolved escalations with prefetched trip. | Reads `Escalation` (status != resolved) | ✅ |
| 4 | **Escalation Audit Log** | `get_escalation_log(trip_id, limit=50)` | Query all escalations, optionally filtered by trip, newest first. | Reads `Escalation` | ✅ |
| 5 | **Timeout Escalation Check** | `check_timeout_escalations()` | Finds active trips (zugewiesen..abgesetzt) whose last TripEvent is older than ESCALATION_TIMEOUT_MINUTES. Creates new Escalation for each with trigger_reason="timeout". Skips if open escalation already exists. | Reads `Trip` (active states), `TripEvent` (last), `Escalation` (existing open); writes `Escalation` | ✅ |

## 4.10 Notification Templates (`core/notification.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **Message Templates** | `Messages` class — Static templates | German message templates: PATIENT_TRIP_BOOKED, PATIENT_DRIVER_ASSIGNED, PATIENT_DRIVER_EN_ROUTE, PATIENT_DRIVER_ARRIVED, PATIENT_DROPPED_OFF, PATIENT_REMINDER, PATIENT_CANCELLED, DRIVER_NEW_TRIP, DRIVER_DAY_SUMMARY, CHEF_ESCALATION, CHEF_DAILY_DASHBOARD. Plus `format_time()` and `format_date()` helpers. | — (templates only) | ✅ |

## 4.11 Live Location (`services/live_location.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **Start Live Location** | `LiveLocationTracker.start(bot, trip_id, chat_id, lat, lon, live_period=3600)` | Sends `send_location` with live_period. Validates coordinates. Stores session (chat_id, message_id) keyed by trip_id. | Reads coords; writes `LiveLocationSession` (in-memory), Telegram location msg | ✅ |
| 2 | **Update Live Location** | `LiveLocationTracker.update(bot, trip_id, lat, lon)` | Edits existing location message via `edit_message_live_location`. Returns False if session missing/inactive/coords invalid. Marks inactive on BadRequest. | Reads `LiveLocationSession`; writes Telegram location edit | ✅ |
| 3 | **Stop Live Location** | `LiveLocationTracker.stop(bot, trip_id)` | Calls `stop_message_live_location`. Removes session from dict. Idempotent (no session → True). | Reads `LiveLocationSession`; writes Telegram stop, session removal | ✅ |
| 4 | **Query Helpers** | `get_session()`, `is_tracking()`, `active_count` | Read-only queries on active sessions. | Reads `LiveLocationSession` dict | ✅ |

## 4.12 Morning Push (`services/morning_push.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **Send Morning Push** | `send_morning_push(app)` | For each driver with trips today (who hasn't been pushed today): builds a morning overview (shift window, trip count, each trip emoji+time+dest, motivational footer). Sends via Telegram bot. Skips drivers already pushed (date-tracked). | Reads `Trip` (today's, with driver+patient), `Driver`; writes Telegram messages | ✅ |
| 2 | **Morning Push Loop** | `run_morning_push_loop(app)` — Background asyncio task | Runs once at startup, then daily at 06:00 local time. Calculates seconds-until-next using naive datetime. | Reads system clock | ✅ |

## 4.13 Billing (`services/billing.py`)

| # | Feature | Trigger | Beschreibung | Data Read/Write | Status |
|---|---------|---------|-------------|-----------------|--------|
| 1 | **Muster-4 PDF Invoice** | `generate_muster4_invoice(data, output_dir)` | DIN-compliant PDF generation with ReportLab. Two-column address window (DIN 5008 window envelope), sender block, recipient (KK), patient info box, itemized trip table (Nr./Datum/Beschreibung/Anz./Einzelpreis/Gesamtpreis), net+7% VAT+gross summary, payment terms, bank details, signature line, page numbers. | Reads `Muster4Data`; writes PDF file | ✅ |
| 2 | **Invoice from Trips** | `generate_invoice_for_trips(trips, ...)` | Converts Trip ORM objects to Muster4Data. Auto-generates invoice number (R-YYYYMMDD-HHMM). Builds line items with vehicle type, fare, sorted by date. Computes Leistungszeitraum. | Reads `Trip` list (with patient/vehicle); writes `Muster4Data` → PDF | ✅ |
| 3 | **CSV Billing Export** | `export_billing_csv(filters, output_dir)` | Queries trips with patient join, applies date/status/billing_status filters. Writes UTF-8-BOM semicolon CSV with 12 columns (invoice number, dates, patient, KK, addresses, fare, status). | Reads `Trip` (with patient); writes CSV file | ✅ |
| 4 | **In-Memory CSV** | `generate_csv_in_memory(trips_data)` | Generates CSV in BytesIO buffer for direct Telegram upload. UTF-8-BOM. | Reads list of dicts | ✅ |

---

# Summary: Features per Bot

## Patient-Bot: 21 features (18 ✅, 2 ⚠️, 0 🔜)

| # | Feature | Status |
|---|---------|--------|
| 1 | Auto-Registration & Welcome (/start) | ✅ |
| 2 | Profile View (/profil) | ✅ |
| 3 | Profile Edit Multi-Step (/profil_edit) | ✅ |
| 4 | Admin Profile Override (/profil_as) | ⚠️ (docstring only, handler not registered) |
| 5 | Template List (/vorlagen) | ✅ |
| 6 | Template Detail (/vorlage_show) | ✅ |
| 7 | Template Create Multi-Step (/vorlage_neu) | ✅ |
| 8 | Template Edit Multi-Step (/vorlage_edit) | ✅ |
| 9 | Template Delete (/vorlage_del) | ✅ |
| 10 | NLU Free-Text Booking | ✅ |
| 11 | Book Intent → Trip Creation | ✅ |
| 12 | Info Intent → Upcoming Trips | ✅ |
| 13 | Recurring/Cancel/Change (stubbed) | ⚠️ |
| 14 | Low Confidence / Rephrase | ✅ |
| 15 | Unregistered Patient Handling | ✅ |
| 16 | Auto-Dispatch on Booking | ✅ |
| 17 | Push Status Notification | ✅ |
| 18 | Live Location Start | ✅ |
| 19 | Live Location Update | ✅ |
| 20 | Live Location Stop | ✅ |
| 21 | State-Change Decision Helpers | ✅ |

## Driver-Bot: 8 features (8 ✅, 0 ⚠️, 0 🔜)

| # | Feature | Status |
|---|---------|--------|
| 1 | Registration Check (/start) | ✅ |
| 2 | Today's Trip Overview (/heute) | ✅ |
| 3 | Break Toggle (/pause) | ✅ |
| 4 | Trip State Transition Keyboards | ✅ |
| 5 | State Transition Execution | ✅ |
| 6 | Send Trip Notification | ✅ |
| 7 | Voice → Transcribe → Intent → Status | ✅ |
| 8 | Natural Language Chat | ✅ |

## Chef-Bot: 18 features (18 ✅, 0 ⚠️, 0 🔜)

| # | Feature | Status |
|---|---------|--------|
| 1 | Help (/start) | ✅ |
| 2 | Daily Dashboard (/dashboard) | ✅ |
| 3 | Manual Assignment (buttons) | ✅ |
| 4 | CSV Billing Export | ✅ |
| 5 | PDF Muster-4 Invoice | ✅ |
| 6 | Driver: Create | ✅ |
| 7 | Driver: List | ✅ |
| 8 | Driver: Update | ✅ |
| 9 | Driver: Soft Delete | ✅ |
| 10 | Vehicle: Create | ✅ |
| 11 | Vehicle: List | ✅ |
| 12 | Vehicle: Update | ✅ |
| 13 | Vehicle: Hard Delete | ✅ |
| 14 | Manual Escalation (/eskalieren) | ✅ |
| 15 | List Open Escalations (/eskalationen) | ✅ |
| 16 | Escalation Audit Log (/eskalation_log) | ✅ |
| 17 | Escalation Option Processing | ✅ |
| 18 | Natural Language Chat | ✅ |

---

## Trigger Type Summary

| Trigger Type | Count | Examples |
|-------------|-------|---------|
| `/command` | 25 | start, profil, profil_edit, vorlagen, vorlage_neu, vorlage_show, vorlage_edit, vorlage_del, heute, pause, dashboard, export, fahrer, fahrzeug, eskalieren, eskalationen, eskalation_log |
| Inline Button | 5 | Trip state transitions, template delete confirm, template create confirm, template field selection, driver assignment, escalation options |
| Natural Language | 3 | Patient booking NLU, Driver chat, Chef chat |
| Voice Message | 1 | Driver voice → transcribe → intent → status |
| System / Scheduled | 3 | Morning push (06:00 daily), timeout escalation check, auto-dispatch on trip creation |
| External API Call | 5 | push_status_update, start/update/stop live tracking, send_trip_to_driver |
