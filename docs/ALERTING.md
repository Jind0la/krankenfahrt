# Alerting — Embedded Prometheus Alerting for Krankenfahrt

## Overview

Krankenfahrt uses an **embedded alerting engine** that evaluates Prometheus metrics
in-process and delivers alerts via Telegram (the app's native notification channel).
No external Prometheus server or Alertmanager is required.

The alerting engine lives in `src/krankenfahrt/alerting.py` and is started
alongside the metrics server in `main.py`.

## Architecture

```
┌─────────────────────────────────────────────┐
│                  main.py                     │
│                                              │
│  ┌──────────────┐   ┌─────────────────────┐ │
│  │ AlertManager  │──▶│ Telegram Notifier   │ │
│  │ (eval loop)   │   │ (Chef bot)          │ │
│  └──────┬───────┘   └─────────┬───────────┘ │
│         │ evaluate             │ send_message│
│  ┌──────▼───────┐              │             │
│  │  Rules        │    ┌────────▼──────────┐ │
│  │  • Deadman    │    │ Admin Telegram     │ │
│  │  • RateRule   │    │ Chat IDs           │ │
│  │  • Threshold  │    └───────────────────┘ │
│  └──────┬───────┘                           │
│         │ read                               │
│  ┌──────▼───────┐                           │
│  │  prometheus   │                           │
│  │  REGISTRY     │                           │
│  └──────────────┘                           │
└─────────────────────────────────────────────┘
```

## Alert Rules

Rules are defined in `main.py` → `_build_alert_rules()`. Each rule is evaluated
every `ALERTING_EVAL_INTERVAL` seconds (default: 30).

### Active Rules

| Rule | Type | Severity | Metric | Threshold |
|------|------|----------|--------|-----------|
| **High HTTP Error Rate** | RateRule | 🔴 Critical | `http_errors_total` | `> ALERTING_ERROR_RATE_THRESHOLD/s` (default: 5.0/s) |
| **Application Heartbeat Missing** | DeadmanSwitch | 🔴 Critical | `krankenfahrt_heartbeat_timestamp_seconds` | No update for `> ALERTING_DEADMAN_MAX_AGE`s (default: 60s) |
| **High LLM Fallback Rate** | RateRule | 🟡 Warning | `krankenfahrt_llm_fallback_total` | `> 0.1/s` for 120s |
| **LLM Retry Storm** | RateRule | 🟡 Warning | `krankenfahrt_llm_retry_total` | `> 0.5/s` for 60s |
| **Database Retry Pressure** | RateRule | 🟡 Warning | `krankenfahrt_db_retry_total` | `> 0.2/s` for 120s |

### Rule Types

#### RateRule
Fires when a Prometheus counter's per-second rate exceeds a threshold
continuously for `duration_seconds`. Requires sustained violation — a brief
spike does not trigger the alert.

```
Eval 1: counter=100   → baseline
Eval 2: counter=150   → rate=50/(T2-T1) > threshold → start timer
Eval 3: counter=200   → rate=50/(T3-T2) > threshold AND elapsed > duration → FIRE
```

#### DeadmanSwitch
Fires when a heartbeat gauge hasn't been updated for `max_age_seconds`.
The heartbeat is bumped every 15s by `_heartbeat_loop()` in main.py.
If the application freezes or crashes, the heartbeat stops updating and
the deadman switch fires.

#### ThresholdRule
Fires when a gauge value exceeds (or falls below) a static threshold
continuously for `duration_seconds`. Supports operators: `gt`, `lt`, `gte`, `lte`.

### Alert Lifecycle

1. **Detection** — rule evaluates, detects violation
2. **Duration** — violation must persist for `duration_seconds`
3. **Firing** — alert fires, notification sent via Telegram
4. **Cooldown** — repeat notifications suppressed for `ALERTING_COOLDOWN` (default: 300s)
5. **Recovery** — when violation ends, a ✅ RESOLVED message is sent

## Configuration

All alerting settings are configurable via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ALERTING_ENABLED` | `1` | Set to `0` to disable alerting |
| `ALERTING_EVAL_INTERVAL` | `30` | Seconds between rule evaluations |
| `ALERTING_COOLDOWN` | `300` | Seconds between repeat notifications |
| `ALERTING_ERROR_RATE_THRESHOLD` | `5.0` | HTTP errors per second threshold |
| `ALERTING_ERROR_RATE_DURATION` | `60` | Seconds violation must persist |
| `ALERTING_DEADMAN_MAX_AGE` | `60` | Seconds without heartbeat before alert |
| `ALERTING_CHEF_CHAT_ID` | `0` | Specific Telegram chat ID for alerts (`0` = all admins) |

### Notification Channels

Alerts are delivered via **Telegram** using the Chef bot (`@FahrtenChef`).
By default, alerts go to all Telegram IDs listed in `ADMIN_TELEGRAM_IDS`.
To send alerts to a specific chat, set `ALERTING_CHEF_CHAT_ID`.

## Testing Alerts

### Simulating a High Error Rate

```python
from krankenfahrt.metrics_server import http_errors_total
import asyncio

# Rapidly increment the error counter
for _ in range(100):
    http_errors_total.labels(method="GET", endpoint="/test").inc()
    await asyncio.sleep(0.1)

# After ALERTING_ERROR_RATE_DURATION seconds, the alert fires
```

### Testing the Deadman Switch

```bash
# Kill the heartbeat loop (simulate freeze)
# After ALERTING_DEADMAN_MAX_AGE seconds (default: 60s), the alert fires
```

### Running the Test Suite

```bash
python -m pytest tests/test_alerting.py -v
```

Tests cover:
- DeadmanSwitch: fires when stale, doesn't fire when fresh
- RateRule: first sample baseline, sustained violation fires, recovery resets
- ThresholdRule: fires after duration, resets on recovery
- AlertManager: triggers notifier, sends recovery, respects cooldown
- Severity emoji formatting

## Adding New Alert Rules

Add rules in `main.py` → `_build_alert_rules()`. Example:

```python
from krankenfahrt.alerting import RateRule, Severity

RateRule(
    name="High Booking Failure Rate",
    description="Booking creation failure rate is elevated",
    metric_name="krankenfahrt_bookings_created_total",  # or a custom counter
    threshold_per_second=1.0,
    operator="gt",
    duration_seconds=300,
    severity=Severity.WARNING,
    cooldown_seconds=600,
)
```

Then add a corresponding Prometheus counter in `metrics_server.py`:

```python
booking_failures_total = Counter(
    "krankenfahrt_booking_failures_total",
    "Total number of failed booking attempts",
)
```
