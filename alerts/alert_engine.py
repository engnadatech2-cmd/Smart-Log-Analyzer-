"""Alert engine: rule evaluation with cooldown and thread-safe callback dispatch.

Evaluates StatsSummary snapshots against configured AlertRule objects and
fires registered callbacks when thresholds are exceeded, while respecting
per-rule cooldown periods.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from alerts.alert_rules import AlertRule
from core.models import AlertEvent, StatsSummary

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(tz=timezone.utc)


def _summary_to_dict(summary: StatsSummary) -> dict[str, float]:
    """Flatten a StatsSummary into a flat metric dict for rule evaluation.

    Args:
        summary: The statistics snapshot to convert.

    Returns:
        A mapping of metric name → numeric value.
    """
    return {
        "total_entries": float(summary.total_entries),
        "error_rate_rpm": summary.error_rate_rpm,
        "window_minutes": float(summary.window_minutes),
    }


class AlertEngine:
    """Evaluates alert rules against rolling statistics snapshots.

    Maintains a cooldown registry so that the same rule does not fire
    repeatedly within its configured cooldown window.  All state shared
    between the evaluation and callback threads is protected by a
    threading.Lock.
    """

    def __init__(self, rules: list[AlertRule]) -> None:
        """Initialise the engine with a list of alert rules.

        Args:
            rules: The alert rules to evaluate on each summary snapshot.
        """
        self._rules = rules
        self._callbacks: list[Callable[[AlertEvent], None]] = []
        self._last_fired: dict[str, datetime] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_alert(self, callback: Callable[[AlertEvent], None]) -> None:
        """Register a callback to be invoked when an alert fires.

        Multiple callbacks may be registered; all are called in
        registration order for each alert event.

        Args:
            callback: A callable that accepts a single AlertEvent argument.
        """
        self._callbacks.append(callback)

    def evaluate(self, summary: StatsSummary) -> None:
        """Evaluate all rules against *summary* and fire callbacks.

        Rules that have fired within their cooldown window are skipped.
        Callbacks are invoked outside the lock to avoid blocking.

        Args:
            summary: The latest statistics snapshot from StatsEngine.
        """
        metrics = _summary_to_dict(summary)
        events_to_fire: list[AlertEvent] = []

        with self._lock:
            now = _utcnow()
            for rule in self._rules:
                value = metrics.get(rule.metric)
                if value is None:
                    continue
                if value <= rule.threshold:
                    continue

                last = self._last_fired.get(rule.name)
                if last is not None:
                    elapsed = (now - last).total_seconds()
                    if elapsed < rule.cooldown_s:
                        continue

                self._last_fired[rule.name] = now
                event = AlertEvent(
                    rule_name=rule.name,
                    severity=rule.severity,
                    message=(
                        f"{rule.metric} = {value:.2f} "
                        f"(threshold: {rule.threshold})"
                    ),
                    value=value,
                    threshold=rule.threshold,
                    timestamp=now,
                )
                events_to_fire.append(event)
                logger.info(
                    "Alert fired: [%s] %s", rule.severity.upper(), rule.name
                )

        # Dispatch callbacks outside the lock
        for event in events_to_fire:
            for cb in self._callbacks:
                try:
                    cb(event)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Alert callback raised an exception: %s", exc
                    )
