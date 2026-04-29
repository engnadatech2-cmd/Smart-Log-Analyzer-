"""Tests for StatsEngine rolling-window statistics."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from analysis.stats_engine import StatsEngine
from core.models import LogEntry, LogLevel
from tests.conftest import make_entry


def _old_entry(seconds_ago: int = 400) -> LogEntry:
    """Return a LogEntry with a timestamp older than the default window."""
    ts = datetime.now(tz=timezone.utc) - timedelta(seconds=seconds_ago)
    return make_entry(level=LogLevel.ERROR, ts=ts)


def _fresh_error() -> LogEntry:
    """Return a fresh ERROR entry timestamped now."""
    return make_entry(level=LogLevel.ERROR)


def _fresh_info() -> LogEntry:
    """Return a fresh INFO entry timestamped now."""
    return make_entry(level=LogLevel.INFO)


class TestWindowEviction:
    """Entries outside the rolling window must be evicted."""

    def test_window_evicts_old_entries(self) -> None:
        """Entries older than window_minutes must not appear in the summary."""
        engine = StatsEngine(window_minutes=5)
        engine.add(_old_entry(seconds_ago=400))  # older than 5 min window
        engine.add(_fresh_info())
        summary = engine.get_summary()
        # Only the fresh entry should remain
        assert summary.total_entries == 1

    def test_fresh_entries_are_retained(self) -> None:
        """Entries within the window must be retained."""
        engine = StatsEngine(window_minutes=5)
        for _ in range(5):
            engine.add(_fresh_info())
        assert engine.get_summary().total_entries == 5


class TestErrorRate:
    """error_rate() must reflect only errors in the last 60 seconds."""

    def test_error_rate_counts_only_recent(self) -> None:
        """Old errors must not inflate the error rate."""
        engine = StatsEngine(window_minutes=10)
        engine.add(_old_entry(seconds_ago=120))  # outside 60-s rate window
        engine.add(_fresh_error())
        engine.add(_fresh_error())
        # Only the two fresh errors should count
        assert engine.error_rate() == 2.0

    def test_error_rate_zero_with_no_errors(self) -> None:
        """Error rate must be 0 when only INFO entries are present."""
        engine = StatsEngine(window_minutes=5)
        for _ in range(10):
            engine.add(_fresh_info())
        assert engine.error_rate() == 0.0


class TestSourceCounts:
    """Source counter must be bounded and accurate after cleanup."""

    def test_source_counts_bounded_after_cleanup(self) -> None:
        """After old entries are evicted, stale sources must disappear."""
        engine = StatsEngine(window_minutes=5)
        # Add an old entry from "old-source"
        old = LogEntry(
            timestamp=datetime.now(tz=timezone.utc) - timedelta(seconds=400),
            level=LogLevel.INFO,
            source="old-source",
            message="msg",
            raw="raw",
        )
        engine.add(old)
        # Add fresh entries from "new-source"
        for _ in range(3):
            engine.add(make_entry(source="new-source"))

        summary = engine.get_summary()
        source_names = [s for s, _ in summary.top_sources]
        assert "old-source" not in source_names
        assert "new-source" in source_names


class TestSummary:
    """get_summary() must return accurate level breakdown."""

    def test_summary_returns_correct_breakdown(self) -> None:
        """Level breakdown must match the ingested entry levels exactly."""
        engine = StatsEngine(window_minutes=5)
        engine.add(_fresh_error())
        engine.add(_fresh_error())
        engine.add(_fresh_info())
        summary = engine.get_summary()
        assert summary.level_breakdown.get("ERROR", 0) == 2
        assert summary.level_breakdown.get("INFO", 0) == 1
        assert summary.total_entries == 3
