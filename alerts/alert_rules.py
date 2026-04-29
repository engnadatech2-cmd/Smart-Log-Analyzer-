"""Alert rule definitions and configuration loader.

Defines the AlertRule dataclass and provides both a default rule set
and a function to load custom rules from the application configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AlertRule:
    """Declarative specification for a single alert rule.

    Attributes:
        name:        Human-readable rule identifier used in AlertEvent.
        metric:      Key into the StatsSummary dict representation.
        threshold:   Numeric threshold; alert fires when metric > threshold.
        severity:    "warning" or "critical".
        cooldown_s:  Minimum seconds between consecutive firings of this rule.
    """

    name: str
    metric: str
    threshold: float
    severity: str
    cooldown_s: int = field(default=60)


# ---------------------------------------------------------------------------
# Default rule set — sensible production defaults
# ---------------------------------------------------------------------------
DEFAULT_RULES: list[AlertRule] = [
    AlertRule(
        name="High Error Rate",
        metric="error_rate_rpm",
        threshold=10.0,
        severity="critical",
        cooldown_s=60,
    ),
    AlertRule(
        name="Elevated Error Rate",
        metric="error_rate_rpm",
        threshold=5.0,
        severity="warning",
        cooldown_s=120,
    ),
    AlertRule(
        name="High Total Errors",
        metric="total_entries",
        threshold=5000,
        severity="warning",
        cooldown_s=300,
    ),
]


def load_rules_from_config(config: dict) -> list[AlertRule]:
    """Build a list of AlertRule objects from the application config dict.

    Reads the ``alert_rules`` key and converts each entry into an
    AlertRule.  If ``alert_rules`` is absent or empty the DEFAULT_RULES
    are returned unchanged.

    Args:
        config: The top-level application configuration dictionary.

    Returns:
        A list of AlertRule instances.
    """
    raw_rules: list[dict] = config.get("alert_rules", [])
    if not raw_rules:
        return DEFAULT_RULES

    rules: list[AlertRule] = []
    for entry in raw_rules:
        rules.append(
            AlertRule(
                name=entry["name"],
                metric=entry["metric"],
                threshold=float(entry["threshold"]),
                severity=entry["severity"],
                cooldown_s=int(entry.get("cooldown_s", 60)),
            )
        )
    return rules
