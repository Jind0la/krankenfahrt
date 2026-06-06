"""Tests for the embedded alerting engine.

Tests cover:
  - DeadmanSwitch: fires when heartbeat is stale
  - RateRule: fires when counter rate exceeds threshold
  - ThresholdRule: fires when gauge exceeds threshold
  - AlertManager: evaluate_now triggers notifier, recovery notifications, cooldown
  - Cooldown prevents repeat notifications
  - Severity emoji formatting
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import pytest
from prometheus_client import Counter, Gauge

from krankenfahrt.alerting import (
    AlertManager,
    AlertRule,
    DeadmanSwitch,
    RateRule,
    Severity,
    ThresholdRule,
)


# ── Helpers ────────────────────────────────────────────────────


class _SpyNotifier:
    """Records all notifications for test assertions."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, alert_name: str, message: str) -> None:
        self.calls.append((alert_name, message))


def _fresh_counter(name: str, labels: Optional[dict[str, str]] = None) -> Counter:
    """Create a new counter with given name, removing any prior registration."""
    from prometheus_client import REGISTRY

    # Unregister if already exists
    collectors = list(REGISTRY._collector_to_names)
    for collector in collectors:
        if hasattr(collector, "_name") and collector._name == name:
            REGISTRY.unregister(collector)

    label_keys = list(labels.keys()) if labels else []
    c = Counter(name, f"Test counter: {name}", label_keys)
    if labels:
        c.labels(**labels)
    return c


def _fresh_gauge(name: str) -> Gauge:
    """Create a new gauge with given name, removing any prior registration."""
    from prometheus_client import REGISTRY

    collectors = list(REGISTRY._collector_to_names)
    for collector in collectors:
        if hasattr(collector, "_name") and collector._name == name:
            REGISTRY.unregister(collector)

    return Gauge(name, f"Test gauge: {name}")


# ── DeadmanSwitch ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_deadman_switch_not_firing_when_fresh():
    """DeadmanSwitch does NOT fire when heartbeat is recent."""
    gauge = _fresh_gauge("test_heartbeat_ts")
    gauge.set(time.monotonic())

    rule = DeadmanSwitch(
        name="Test Deadman",
        description="Test",
        metric_name="test_heartbeat_ts",
        max_age_seconds=60,
    )

    firing, detail = await rule.evaluate()
    assert not firing
    assert "OK" in detail


@pytest.mark.asyncio
async def test_deadman_switch_fires_when_stale():
    """DeadmanSwitch fires when heartbeat is older than max_age."""
    gauge = _fresh_gauge("test_heartbeat_stale")
    gauge.set(time.monotonic() - 120)  # 2 minutes ago

    rule = DeadmanSwitch(
        name="Test Deadman",
        description="Test",
        metric_name="test_heartbeat_stale",
        max_age_seconds=60,
    )

    firing, detail = await rule.evaluate()
    assert firing
    assert "No heartbeat" in detail


@pytest.mark.asyncio
async def test_deadman_switch_not_found():
    """DeadmanSwitch returns False when metric doesn't exist."""
    rule = DeadmanSwitch(
        name="Test Deadman",
        description="Test",
        metric_name="nonexistent_metric_xyz",
        max_age_seconds=60,
    )

    firing, detail = await rule.evaluate()
    assert not firing
    assert "not found" in detail.lower() or "not initialized" in detail.lower()


# ── RateRule ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_rule_first_sample_no_fire():
    """RateRule needs two samples — first eval does not fire."""
    counter = _fresh_counter("test_rate_counter")
    counter.inc(0)  # start at 0

    rule = RateRule(
        name="Test Rate",
        description="Test",
        metric_name="test_rate_counter",
        threshold_per_second=1.0,
        operator="gt",
        duration_seconds=10,
    )

    firing, detail = await rule.evaluate()
    assert not firing
    assert "First sample" in detail or "Need another" in detail


@pytest.mark.asyncio
async def test_rate_rule_fires_after_duration():
    """RateRule fires after violation persists for duration_seconds."""
    counter = _fresh_counter("test_rate_fire")
    counter.inc(0)

    rule = RateRule(
        name="Test Rate",
        description="Test",
        metric_name="test_rate_fire",
        threshold_per_second=1.0,
        operator="gt",
        duration_seconds=0.1,
    )

    # First sample — baseline
    firing, detail = await rule.evaluate()
    assert not firing

    # Increment counter
    counter.inc(50)
    await asyncio.sleep(0.05)

    # Second evaluation — detects violation, starts timer
    firing, detail = await rule.evaluate()
    assert not firing  # duration not yet met

    # Increment MORE (sustained high rate)
    counter.inc(50)
    await asyncio.sleep(0.15)

    # Third evaluation — violation persisted with ongoing increments
    firing, detail = await rule.evaluate()
    assert firing, f"Expected firing=True, got: {detail}"


@pytest.mark.asyncio
async def test_rate_rule_resets_on_recovery():
    """RateRule resets violation timer when rate drops back below threshold."""
    counter = _fresh_counter("test_rate_reset")
    counter.inc(0)

    rule = RateRule(
        name="Test Rate",
        description="Test",
        metric_name="test_rate_reset",
        threshold_per_second=100.0,  # very high threshold
        operator="gt",
        duration_seconds=0.1,
    )

    # First sample
    await rule.evaluate()

    # Small increment — rate below threshold
    counter.inc(1)
    await asyncio.sleep(0.15)

    firing, detail = await rule.evaluate()
    assert not firing
    assert "OK" in detail


# ── ThresholdRule ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_threshold_rule_fires_after_duration():
    """ThresholdRule fires after gauge exceeds threshold for duration."""
    gauge = _fresh_gauge("test_threshold_gauge")
    gauge.set(0)

    rule = ThresholdRule(
        name="Test Threshold",
        description="Test",
        metric_name="test_threshold_gauge",
        threshold=5.0,
        operator="gt",
        duration_seconds=0.1,
    )

    # Below threshold — should not fire
    firing, detail = await rule.evaluate()
    assert not firing

    # Set above threshold
    gauge.set(10.0)

    # First evaluation detects violation, but duration not yet met
    firing, detail = await rule.evaluate()
    assert not firing
    assert "Violation detected" in detail or "Waiting" in detail

    # Wait for duration
    await asyncio.sleep(0.15)

    # Should now fire
    firing, detail = await rule.evaluate()
    assert firing, f"Expected firing=True, got: {detail}"


@pytest.mark.asyncio
async def test_threshold_rule_resets():
    """ThresholdRule resets violation timer when value drops back below threshold."""
    gauge = _fresh_gauge("test_threshold_reset")
    gauge.set(10.0)  # above threshold

    rule = ThresholdRule(
        name="Test Threshold",
        description="Test",
        metric_name="test_threshold_reset",
        threshold=5.0,
        operator="gt",
        duration_seconds=60.0,  # long duration
    )

    # Violation starts
    firing, detail = await rule.evaluate()
    assert not firing  # duration not met

    # Drop below threshold
    gauge.set(3.0)

    firing, detail = await rule.evaluate()
    assert not firing
    assert "OK" in detail  # reset


# ── AlertManager ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_manager_triggers_notifier():
    """AlertManager fires notifier when a rule transitions to firing."""
    gauge = _fresh_gauge("test_am_gauge")
    gauge.set(time.monotonic() - 120)  # stale heartbeat

    rule = DeadmanSwitch(
        name="AM Deadman",
        description="Test deadman",
        metric_name="test_am_gauge",
        max_age_seconds=60,
        severity=Severity.CRITICAL,
        cooldown_seconds=1.0,  # short cooldown for test
    )

    spy = _SpyNotifier()
    manager = AlertManager(rules=[rule], notifier=spy, eval_interval=999)

    await manager.evaluate_now()

    assert len(spy.calls) >= 1, f"Expected at least 1 notification, got {spy.calls}"
    alert_name, message = spy.calls[0]
    assert alert_name == "AM Deadman"
    assert "🔴" in message  # critical emoji


@pytest.mark.asyncio
async def test_alert_manager_sends_recovery():
    """AlertManager sends recovery notification when alert resolves."""
    gauge = _fresh_gauge("test_am_recovery")
    gauge.set(time.monotonic() - 120)  # stale

    rule = DeadmanSwitch(
        name="AM Recovery",
        description="Test recovery",
        metric_name="test_am_recovery",
        max_age_seconds=60,
        severity=Severity.CRITICAL,
        cooldown_seconds=1.0,
    )

    spy = _SpyNotifier()
    manager = AlertManager(rules=[rule], notifier=spy, eval_interval=999)

    # First eval — should fire
    await manager.evaluate_now()
    assert len(spy.calls) >= 1
    assert any("RESOLVED" not in msg for _, msg in spy.calls), (
        "Expected firing alert (not resolved)"
    )

    # Heal the heartbeat
    gauge.set(time.monotonic())

    # Second eval — should resolve
    await manager.evaluate_now()

    recovery_calls = [
        (name, msg)
        for name, msg in spy.calls
        if "RESOLVED" in msg
    ]
    assert len(recovery_calls) >= 1, (
        f"Expected recovery notification, got calls: {spy.calls}"
    )


@pytest.mark.asyncio
async def test_cooldown_prevents_repeat_notifications():
    """AlertManager respects cooldown — no repeat notifications within cooldown window."""
    gauge = _fresh_gauge("test_am_cooldown")
    gauge.set(time.monotonic() - 120)

    rule = DeadmanSwitch(
        name="AM Cooldown",
        description="Test cooldown",
        metric_name="test_am_cooldown",
        max_age_seconds=60,
        severity=Severity.WARNING,
        cooldown_seconds=10.0,  # 10s cooldown
    )

    spy = _SpyNotifier()
    manager = AlertManager(rules=[rule], notifier=spy, eval_interval=999)

    # First eval — fires + notifies
    await manager.evaluate_now()
    first_call_count = len(spy.calls)
    assert first_call_count >= 1

    # Second eval immediately — still firing, but cooldown blocks notification
    await manager.evaluate_now()
    assert len(spy.calls) == first_call_count, (
        f"Cooldown should block repeat notification. "
        f"Had {first_call_count}, now {len(spy.calls)}"
    )


@pytest.mark.asyncio
async def test_active_alerts_property():
    """AlertManager.active_alerts reflects currently firing rules."""
    gauge = _fresh_gauge("test_active_alerts")
    gauge.set(time.monotonic() - 120)

    rule = DeadmanSwitch(
        name="Active Test",
        description="Test",
        metric_name="test_active_alerts",
        max_age_seconds=60,
    )

    spy = _SpyNotifier()
    manager = AlertManager(rules=[rule], notifier=spy)

    await manager.evaluate_now()

    active = manager.active_alerts
    assert len(active) == 1
    assert active[0]["name"] == "Active Test"
    assert active[0]["severity"] == "critical"


# ── Severity format ────────────────────────────────────────────


def test_severity_emoji_formatting():
    """Alert messages include the correct severity emoji."""
    rule = DeadmanSwitch(
        name="Emoji Test",
        description="Test description",
        metric_name="test_emoji",
        max_age_seconds=60,
        severity=Severity.CRITICAL,
    )
    msg = rule.format_alert("Something is wrong")
    assert "🔴" in msg, f"Critical severity should have 🔴 emoji: {msg}"
    assert "**Emoji Test**" in msg
    assert "critical" in msg.lower()
    assert "Something is wrong" in msg

    rule_warn = DeadmanSwitch(
        name="Warn Test",
        description="Test",
        metric_name="test_warn",
        max_age_seconds=60,
        severity=Severity.WARNING,
    )
    msg_warn = rule_warn.format_alert("Warning detail")
    assert "🟡" in msg_warn, f"Warning severity should have 🟡 emoji: {msg_warn}"


# ── Tear down ──────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _cleanup_registry():
    """Clean up test metrics from the global registry after each test."""
    yield
    from prometheus_client import REGISTRY

    test_names = [
        n for n in [
            "test_heartbeat_ts",
            "test_heartbeat_stale",
            "test_rate_counter",
            "test_rate_fire",
            "test_rate_reset",
            "test_threshold_gauge",
            "test_threshold_reset",
            "test_am_gauge",
            "test_am_recovery",
            "test_am_cooldown",
            "test_active_alerts",
            "test_emoji",
            "test_warn",
        ]
    ]
    collectors = list(REGISTRY._collector_to_names)
    for collector in collectors:
        if hasattr(collector, "_name") and collector._name in test_names:
            REGISTRY.unregister(collector)
