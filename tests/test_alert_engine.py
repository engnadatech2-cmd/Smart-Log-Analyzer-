"""Tests for AlertEngine rule evaluation and cooldown logic."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from alerts.alert_engine import AlertEngine
from alerts.alert_rules import AlertRule
from core.models import AlertEvent, StatsSummary


def _make_summary(error_rate: float = 0.0, total: int = 0) -> StatsSummary:
    """Build a minimal StatsSummary for testing."""
    return StatsSummary(
        total_entries=total,
        error_rate_rpm=error_rate,
        level_breakdown={},
        top_sources=[],
        window_minutes=5,
        captured_at=datetime.now(tz=timezone.utc),
    )


class TestRuleFiring:
    def test_rule_fires_when_threshold_exceeded(self) -> None:
        """A metric above threshold must trigger the callback exactly once."""
        rule = AlertRule("Test Rule", "error_rate_rpm", 5.0, "critical", 0)
        engine = AlertEngine(rules=[rule])
        fired: list[AlertEvent] = []
        engine.on_alert(fired.append)
        engine.evaluate(_make_summary(error_rate=10.0))
        assert len(fired) == 1
        assert fired[0].rule_name == "Test Rule"

    def test_rule_does_not_fire_below_threshold(self) -> None:
        """A metric at the threshold must NOT trigger the callback."""
        rule = AlertRule("Low Threshold", "error_rate_rpm", 5.0, "warning", 0)
        engine = AlertEngine(rules=[rule])
        fired: list[AlertEvent] = []
        engine.on_alert(fired.append)
        engine.evaluate(_make_summary(error_rate=5.0))
        assert len(fired) == 0


class TestCooldown:
    def test_cooldown_prevents_duplicate_alerts(self) -> None:
        """Two evaluations within cooldown_s must produce only one alert."""
        rule = AlertRule("Cooldown Rule", "error_rate_rpm", 1.0, "warning", 60)
        engine = AlertEngine(rules=[rule])
        fired: list[AlertEvent] = []
        engine.on_alert(fired.append)
        engine.evaluate(_make_summary(error_rate=10.0))
        engine.evaluate(_make_summary(error_rate=10.0))
        assert len(fired) == 1

    def test_cooldown_zero_fires_every_time(self) -> None:
        """With cooldown_s=0, every evaluation above threshold must fire."""
        rule = AlertRule("No Cooldown", "error_rate_rpm", 1.0, "critical", 0)
        engine = AlertEngine(rules=[rule])
        fired: list[AlertEvent] = []
        engine.on_alert(fired.append)
        engine.evaluate(_make_summary(error_rate=10.0))
        engine.evaluate(_make_summary(error_rate=10.0))
        assert len(fired) == 2


class TestMultipleCallbacks:
    def test_multiple_callbacks_all_called(self) -> None:
        """All three registered callbacks must receive the alert event."""
        rule = AlertRule("Multi CB Rule", "error_rate_rpm", 1.0, "warning", 0)
        engine = AlertEngine(rules=[rule])
        results: list[str] = []
        engine.on_alert(lambda e: results.append("A"))
        engine.on_alert(lambda e: results.append("B"))
        engine.on_alert(lambda e: results.append("C"))
        engine.evaluate(_make_summary(error_rate=5.0))
        assert results == ["A", "B", "C"]
