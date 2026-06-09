# Logging & Monitoring — Krankenfahrt

Consolidated overview of the four integrated subsystems: structured logging,
health checks, Prometheus metrics, and embedded alerting.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py (entry point)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │ setup_logging│  │ HealthServer │  │   MetricsServer       │ │
│  │ (structlog)  │  │ :8080        │  │   :9090               │ │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬───────────┘ │
│         │                 │                      │              │
│         │            GET /health             GET /metrics      │
│         │            GET /healthz            GET /health       │
│         │                                                      │
│  ┌──────┴──────────────────────────────────────────────────┐   │
│  │              AlertManager (embedded)                      │   │
│  │  Evaluates PROMETHEUS REGISTRY in-process                │   │
│  │  5 rules → Telegram notifications via Chef bot           │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

## 1. Structured Logging (structlog)

**File:** `src/krankenfahrt/logging_setup.py`

- JSON output by default (`LOG_FORMAT=json`), console mode available (`LOG_FORMAT=console`)
- All log entries carry: `timestamp`, `level`, `logger`, `event`
- Exception tracebacks automatically included via `format_exc_info`
- Log level controlled by `LOG_LEVEL` env var (default: INFO)
- 9 noisy third-party loggers silenced (apscheduler, asyncio, httpx, tortoise, etc.)

**Modules wired:**
- 13 modules use `structlog.get_logger()` directly
- 10 modules use stdlib `logging.getLogger()` (routed through structlog's `foreign_pre_chain`)
- All output is structured JSON regardless of which API the module uses

**Verification:** `python tests/verify_structlog.py` produces valid JSON with all fields.

## 2. Health Check Server

**File:** `src/krankenfahrt/health.py`
**Port:** 8080 (configurable via `HEALTH_PORT`)

- `GET /health` → `{"status": "ok", "uptime": <seconds>, "database": "connected"}`
- `GET /healthz` → same (K8s-style alias)
- Optional database liveness probe via `db_check` callable
- Returns 503 if database is disconnected
- Minimal async HTTP server (no aiohttp dependency)
- Railway/Fly.io compatible

## 3. Prometheus Metrics

**File:** `src/krankenfahrt/metrics_server.py`
**Port:** 9090 (configurable via `METRICS_PORT`)

### HTTP Metrics (auto-tracked by middleware)
| Metric | Type | Labels |
|--------|------|--------|
| `http_requests_total` | Counter | method, endpoint, status |
| `http_request_duration_seconds` | Histogram | method, endpoint |
| `http_errors_total` | Counter | method, endpoint |

### App-Specific Metrics
| Metric | Type | Labels |
|--------|------|--------|
| `krankenfahrt_trips_total` | Counter | status |
| `krankenfahrt_active_drivers` | Gauge | — |
| `krankenfahrt_escalations_total` | Counter | — |
| `krankenfahrt_bookings_created_total` | Counter | — |
| `krankenfahrt_voice_messages_processed` | Counter | — |
| `krankenfahrt_whisper_processing_seconds` | Histogram | — |
| `krankenfahrt_llm_requests_total` | Counter | operation |
| `krankenfahrt_llm_request_duration_seconds` | Histogram | operation |
| `krankenfahrt_dispatch_attempts_total` | Counter | engine |

### Resilience Metrics
| Metric | Type | Labels |
|--------|------|--------|
| `krankenfahrt_llm_fallback_total` | Counter | primary_provider, fallback_provider |
| `krankenfahrt_llm_retry_total` | Counter | provider |
| `krankenfahrt_db_retry_total` | Counter | operation |
| `krankenfahrt_rate_limiter_deferred_total` | Counter | — |
| `krankenfahrt_rate_limiter_timeout_total` | Counter | — |

### Heartbeat
| Metric | Type | Purpose |
|--------|------|---------|
| `krankenfahrt_heartbeat_timestamp_seconds` | Gauge | Deadman switch — bumped every 15s by `_heartbeat_loop()` |

**API:** `bump_heartbeat()` function updates the heartbeat gauge. Called by main loop every 15 seconds.

## 4. Embedded Alerting

**File:** `src/krankenfahrt/alerting.py`

Evaluates the Prometheus `REGISTRY` in-process — no external Alertmanager required.
Notifications delivered via Telegram (Chef bot).

### Rule Types
| Type | Description |
|------|-------------|
| `ThresholdRule` | Fires when gauge exceeds/falls below threshold for N seconds |
| `RateRule` | Fires when counter's per-second rate exceeds threshold for N seconds |
| `DeadmanSwitch` | Fires when heartbeat metric goes stale (application frozen) |

### Active Rules (5)
| Rule | Severity | Metric | Trigger |
|------|----------|--------|---------|
| High HTTP Error Rate | 🔴 CRITICAL | `http_errors_total` | Rate > 0.1/s for 60s |
| Application Heartbeat Missing | 🔴 CRITICAL | `krankenfahrt_heartbeat_timestamp_seconds` | Age > 60s |
| High LLM Fallback Rate | 🟡 WARNING | `krankenfahrt_llm_fallback_total` | Rate > 0.1/s for 120s |
| LLM Retry Storm | 🟡 WARNING | `krankenfahrt_llm_retry_total` | Rate > 0.5/s for 60s |
| Database Retry Pressure | 🟡 WARNING | `krankenfahrt_db_retry_total` | Rate > 0.2/s for 120s |

### Features
- Sustained violation (3+ evaluations) required — prevents false positives
- Recovery notifications with 🟢 emoji when alert resolves
- Cooldown: 300s between repeat notifications per rule (configurable)
- All parameters env-configurable via `ALERTING_*` variables

## Configuration Reference

### Health Server
| Env Var | Default | Description |
|---------|---------|-------------|
| `HEALTH_HOST` | `0.0.0.0` | Bind address |
| `HEALTH_PORT` | `8080` | Listen port |

### Metrics Server
| Env Var | Default | Description |
|---------|---------|-------------|
| `METRICS_PORT` | `9090` | Listen port |

### Alerting
| Env Var | Default | Description |
|---------|---------|-------------|
| `ALERTING_ENABLED` | `0` | Enable alerting (`1` = on) |
| `ALERTING_EVAL_INTERVAL` | `30.0` | Seconds between rule evaluations |
| `ALERTING_CHEF_CHAT_ID` | `0` | Specific chat ID for alerts (0 = use ADMIN_TELEGRAM_IDS) |
| `ALERTING_ERROR_RATE_THRESHOLD` | `0.1` | HTTP errors/second to trigger |
| `ALERTING_ERROR_RATE_DURATION` | `60.0` | Seconds violation must persist |
| `ALERTING_COOLDOWN` | `300.0` | Seconds between repeat notifications |
| `ALERTING_DEADMAN_MAX_AGE` | `60.0` | Max heartbeat age before deadman fires |

### Logging
| Env Var | Default | Description |
|---------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Python log level |
| `LOG_FORMAT` | `json` | Output format (`json` or `console`) |

## Test Coverage

| Component | Tests | Status |
|-----------|-------|--------|
| Health Server | 5 | ✅ All pass |
| Metrics Server | 5 | ✅ All pass |
| Alerting Engine | 13 | ✅ All pass |
| Config | 2 | ✅ All pass |
| Structlog Verification | 1 | ✅ Valid JSON |

**Total:** 25/25 logging & monitoring tests pass.
**Full suite:** 511/514 pass (3 pre-existing patient_bot auth failures unrelated).

## Integration Points Fixed

During consolidation, two integration gaps were identified and resolved:

1. **`bump_heartbeat()` missing from metrics_server.py** — added heartbeat gauge + bump function so the deadman switch has a metric to monitor
2. **Alerting config fields missing from config.py** — added 7 `ALERTING_*` fields with sensible defaults so `main.py` can reference them
