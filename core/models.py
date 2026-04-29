"""Core data models for the Smart Log Analyzer.

Defines immutable, memory-efficient dataclasses for log entries,
alert events, and statistics summaries.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class LogLevel(Enum):
    """Enumeration of log severity levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class LogEntry:
    """Represents a single parsed log line.

    All fields are immutable for safe cross-thread sharing.
    """

    timestamp: datetime
    level: LogLevel
    source: str
    message: str
    raw: str


@dataclass(frozen=True, slots=True)
class AlertEvent:
    """Represents a fired alert from the alert engine.

    Contains the rule metadata, observed value, and threshold that
    triggered the alert.
    """

    rule_name: str
    severity: str          # "warning" | "critical"
    message: str
    value: float
    threshold: float
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class StatsSummary:
    """A snapshot of rolling statistics over the configured time window.

    Produced by StatsEngine and consumed by the dashboard, API, and
    alert engine.
    """

    total_entries: int
    error_rate_rpm: float
    level_breakdown: dict[str, int]
    top_sources: list[tuple[str, int]]
    window_minutes: int
    captured_at: datetime
