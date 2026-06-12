"""Embedded alerting engine for Krankenfahrt metrics.

Evaluates Prometheus metrics in-process and fires alerts via Telegram
(the app's native notification channel). No external Alertmanager required.

Alert types:
  - ThresholdRule: fires when a metric exceeds a threshold for N seconds
  - DeadmanSwitch: fires when a heartbeat metric stops being updated
  - RateRule: fires when a counter's rate exceeds a threshold

Usage:
    from krankenfahrt.alerting import AlertManager, ThresholdRule, DeadmanSwitch

    manager = AlertManager(
        rules=[...],
        notifier=my_telegram_sender,
        eval_interval=30,
    )
    await manager.start()
    ...
    await manager.stop()
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from prometheus_client import REGISTRY

logger = logging.getLogger(__name__)

# ── Type aliases ────────────────────────────────────────────────
Notifier = Callable[[str, str], Awaitable[None]]
# notifier(alert_name: str, message: str) -> None


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


# ── Alert definition ────────────────────────────────────────────

@dataclass
class AlertState:
    """Mutable state tracked per rule by AlertManager."""

    firing: bool = False
    since: float = 0.0  # monotonic timestamp when first fired
    last_notified: float = 0.0  # monotonic timestamp of last notification
    cooldown_seconds: float = 300.0  # min seconds between repeat notifications

    def should_notify(self, now: float) -> bool:
        if not self.firing:
            return False
        if self.last_notified == 0.0:
            return True  # first notification
        return (now - self.last_notified) >= self.cooldown_seconds

    def mark_notified(self, now: float) -> None:
        self.last_notified = now


# ── Rules ────────────────────────────────────────────────────────


class AlertRule(ABC):
    """Base class for all alerting rules."""

    def __init__(
        self,
        name: str,
        description: str,
        severity: Severity = Severity.WARNING,
        cooldown_seconds: float = 300.0,
    ) -> None:
        self.name = name
        self.description = description
        self.severity = severity
        self.cooldown_seconds = cooldown_seconds

    @abstractmethod
    async def evaluate(self) -> tuple[bool, str]:
        """Return (firing, detail_message)."""

    def format_alert(self, detail: str) -> str:
        """Produce a human-readable alert message."""
        emoji = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(
            self.severity.value, "⚠️"
        )
        return (
            f"{emoji} **{self.name}** ({self.severity.value})\n\n"
            f"{self.description}\n\n"
            f"{detail}"
        )


class ThresholdRule(AlertRule):
    """Fires when a Prometheus metric exceeds (or falls below) a threshold.

    The condition must persist for `duration_seconds` before the alert fires.
    """

    def __init__(
        self,
        name: str,
        description: str,
        metric_name: str,
        threshold: float,
        operator: str = "gt",  # "gt" | "lt" | "gte" | "lte"
        duration_seconds: float = 60.0,
        labels: dict[str, str] | None = None,
        severity: Severity = Severity.WARNING,
        cooldown_seconds: float = 300.0,
    ) -> None:
        super().__init__(name, description, severity, cooldown_seconds)
        self.metric_name = metric_name
        self.threshold = threshold
        self.operator = operator
        self.duration_seconds = duration_seconds
        self.labels = labels or {}

        self._first_violation_at: float = 0.0  # monotonic

    def _get_value(self) -> float | None:
        """Read the current value from the Prometheus registry."""
        try:
            # Collect all metrics matching this name
            for metric in REGISTRY.collect():
                if metric.name == self.metric_name:
                    if not metric.samples:
                        return None
                    # If labels specified, find the matching sample
                    if self.labels:
                        for sample in metric.samples:
                            if all(
                                sample.labels.get(k) == v
                                for k, v in self.labels.items()
                            ):
                                return sample.value
                        return None  # no matching labels
                    # No label filter — return first sample value
                    return metric.samples[0].value if metric.samples else None
            return None  # metric not found
        except Exception:
            logger.debug(
                "Failed to read metric %s", self.metric_name, exc_info=True
            )
            return None

    def _check_threshold(self, value: float) -> bool:
        match self.operator:
            case "gt":
                return value > self.threshold
            case "lt":
                return value < self.threshold
            case "gte":
                return value >= self.threshold
            case "lte":
                return value <= self.threshold
            case _:
                raise ValueError(f"Unknown operator: {self.operator}")

    async def evaluate(self) -> tuple[bool, str]:
        now = time.monotonic()
        value = self._get_value()

        if value is None:
            return False, (
                f"Metric `{self.metric_name}` not found in registry "
                f"(labels={self.labels}). Cannot evaluate."
            )

        is_violating = self._check_threshold(value)

        if not is_violating:
            self._first_violation_at = 0.0
            return False, (
                f"OK — `{self.metric_name}` = {value:.4g} "
                f"(threshold: {self.operator} {self.threshold})"
            )

        if self._first_violation_at == 0.0:
            self._first_violation_at = now
            return False, (
                f"Violation detected — `{self.metric_name}` = {value:.4g} "
                f"(threshold: {self.operator} {self.threshold}). "
                f"Waiting {self.duration_seconds}s before firing."
            )

        elapsed = now - self._first_violation_at
        if elapsed < self.duration_seconds:
            return False, (
                f"Violation persists ({elapsed:.0f}s / {self.duration_seconds}s). "
                f"`{self.metric_name}` = {value:.4g}"
            )

        return True, (
            f"`{self.metric_name}` = {value:.4g} "
            f"(threshold: {self.operator} {self.threshold}, "
            f"duration: {elapsed:.0f}s)"
        )


class RateRule(AlertRule):
    """Fires when a counter's per-second rate exceeds a threshold.

    Computes (current - previous) / elapsed from the last evaluation.
    Requires at least two evaluations to produce a rate.
    """

    def __init__(
        self,
        name: str,
        description: str,
        metric_name: str,
        threshold_per_second: float,
        operator: str = "gt",
        duration_seconds: float = 60.0,
        labels: dict[str, str] | None = None,
        severity: Severity = Severity.WARNING,
        cooldown_seconds: float = 300.0,
    ) -> None:
        super().__init__(name, description, severity, cooldown_seconds)
        self.metric_name = metric_name
        self.threshold_per_second = threshold_per_second
        self.operator = operator
        self.duration_seconds = duration_seconds
        self.labels = labels or {}

        self._first_violation_at: float = 0.0
        self._previous_value: float | None = None
        self._previous_time: float = 0.0

    def _get_value(self) -> float | None:
        try:
            for metric in REGISTRY.collect():
                if metric.name == self.metric_name:
                    if not metric.samples:
                        return None
                    if self.labels:
                        for sample in metric.samples:
                            if all(
                                sample.labels.get(k) == v
                                for k, v in self.labels.items()
                            ):
                                return sample.value
                        return None
                    return metric.samples[0].value if metric.samples else None
            return None
        except Exception:
            return None

    async def evaluate(self) -> tuple[bool, str]:
        now = time.monotonic()
        value = self._get_value()

        if value is None:
            return False, (
                f"Metric `{self.metric_name}` not found in registry."
            )

        if self._previous_value is None:
            self._previous_value = value
            self._previous_time = now
            return False, (
                f"First sample — `{self.metric_name}` = {value:.4g}. "
                f"Need another evaluation to compute rate."
            )

        elapsed = now - self._previous_time
        if elapsed <= 0:
            return False, "Zero elapsed time — skipping rate computation."

        rate = (value - self._previous_value) / elapsed
        self._previous_value = value
        self._previous_time = now

        is_violating = (
            rate > self.threshold_per_second
            if self.operator == "gt"
            else rate < self.threshold_per_second
        )

        if not is_violating:
            self._first_violation_at = 0.0
            return False, (
                f"OK — `{self.metric_name}` rate = {rate:.4g}/s "
                f"(threshold: {self.operator} {self.threshold_per_second}/s)"
            )

        if self._first_violation_at == 0.0:
            self._first_violation_at = now

        violation_elapsed = now - self._first_violation_at
        if violation_elapsed < self.duration_seconds:
            return False, (
                f"Rate violation persists ({violation_elapsed:.0f}s / "
                f"{self.duration_seconds}s). "
                f"`{self.metric_name}` rate = {rate:.4g}/s"
            )

        return True, (
            f"`{self.metric_name}` rate = {rate:.4g}/s "
            f"(threshold: {self.operator} {self.threshold_per_second}/s, "
            f"duration: {violation_elapsed:.0f}s)"
        )


class DeadmanSwitch(AlertRule):
    """Fires when a metric hasn't been updated in `max_age_seconds`.

    Designed for a heartbeat gauge that gets bumped regularly (e.g. every 15s).
    If the heartbeat is older than max_age, the app is likely down or frozen.

    The heartbeat gauge stores a monotonic timestamp; this rule compares
    against the current time.
    """

    def __init__(
        self,
        name: str,
        description: str,
        metric_name: str = "krankenfahrt_heartbeat_timestamp_seconds",
        max_age_seconds: float = 60.0,
        severity: Severity = Severity.CRITICAL,
        cooldown_seconds: float = 300.0,
    ) -> None:
        super().__init__(name, description, severity, cooldown_seconds)
        self.metric_name = metric_name
        self.max_age_seconds = max_age_seconds

    def _get_heartbeat_age(self) -> float | None:
        """Return seconds since last heartbeat, or None if not found."""
        try:
            for metric in REGISTRY.collect():
                if metric.name == self.metric_name:
                    if not metric.samples:
                        return None
                    last_timestamp = metric.samples[0].value
                    if last_timestamp <= 0:
                        return None  # not initialized yet
                    return time.monotonic() - last_timestamp
            return None
        except Exception:
            return None

    async def evaluate(self) -> tuple[bool, str]:
        age = self._get_heartbeat_age()

        if age is None:
            return False, (
                f"Metric `{self.metric_name}` not found or not initialized."
            )

        if age < self.max_age_seconds:
            return False, (
                f"OK — last heartbeat {age:.1f}s ago "
                f"(max age: {self.max_age_seconds}s)"
            )

        return True, (
            f"No heartbeat for {age:.1f}s "
            f"(max age: {self.max_age_seconds}s). "
            f"Application may be down or frozen."
        )


# ── Alert Manager ────────────────────────────────────────────────


class AlertManager:
    """Orchestrates rule evaluation and notification delivery."""

    def __init__(
        self,
        rules: list[AlertRule],
        notifier: Notifier,
        eval_interval: float = 30.0,
    ) -> None:
        self.rules = rules
        self.notifier = notifier
        self.eval_interval = eval_interval

        self._task: asyncio.Task[None] | None = None
        self._states: dict[str, AlertState] = {}
        self._running = False

        # Initialize state for each rule
        for rule in rules:
            self._states[rule.name] = AlertState(
                cooldown_seconds=rule.cooldown_seconds,
            )

    async def start(self) -> None:
        """Begin periodic evaluation loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._eval_loop())
        logger.info(
            "AlertManager started — %d rules, interval %ds",
            len(self.rules),
            self.eval_interval,
        )

    async def stop(self) -> None:
        """Stop the evaluation loop."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("AlertManager stopped")

    async def evaluate_now(self) -> list[tuple[AlertRule, bool, str]]:
        """Force-immediate evaluation. Returns list of (rule, firing, detail)."""
        results: list[tuple[AlertRule, bool, str]] = []
        now = time.monotonic()

        for rule in self.rules:
            state = self._states[rule.name]

            try:
                firing, detail = await rule.evaluate()
            except Exception:
                logger.exception(
                    "Error evaluating rule %s", rule.name
                )
                continue

            results.append((rule, firing, detail))

            # Transition tracking
            was_firing = state.firing
            state.firing = firing

            if firing and not was_firing:
                state.since = now
                logger.warning(
                    "Alert FIRING: %s — %s", rule.name, detail
                )
            elif not firing and was_firing:
                logger.info(
                    "Alert RESOLVED: %s — %s", rule.name, detail
                )
                state.since = 0.0
                state.last_notified = 0.0
                # Send recovery notification
                try:
                    emoji = {"critical": "🟢", "warning": "🟢", "info": "🟢"}.get(
                        rule.severity.value, "✅"
                    )
                    await self.notifier(
                        rule.name,
                        f"{emoji} **RESOLVED: {rule.name}**\n\n{detail}",
                    )
                except Exception:
                    logger.exception(
                        "Failed to send recovery notification for %s",
                        rule.name,
                    )

            # Notification
            if state.firing and state.should_notify(now):
                try:
                    await self.notifier(
                        rule.name,
                        rule.format_alert(detail),
                    )
                    state.mark_notified(now)
                except Exception:
                    logger.exception(
                        "Failed to send alert notification for %s",
                        rule.name,
                    )

        return results

    async def _eval_loop(self) -> None:
        """Periodic evaluation loop."""
        while self._running:
            await self.evaluate_now()
            await asyncio.sleep(self.eval_interval)

    @property
    def active_alerts(self) -> list[dict[str, Any]]:
        """Return list of currently firing alerts."""
        active: list[dict[str, Any]] = []
        for rule in self.rules:
            state = self._states.get(rule.name)
            if state and state.firing:
                active.append({
                    "name": rule.name,
                    "severity": rule.severity.value,
                    "firing_since": state.since,
                    "description": rule.description,
                })
        return active
