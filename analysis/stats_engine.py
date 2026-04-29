"""Rolling-window statistics engine.

Maintains bounded internal structures and computes error rates and
level/source breakdowns over a configurable sliding time window.
"""
from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from core.models import LogEntry, LogLevel, StatsSummary

logger = logging.getLogger(__name__)

# Maximum entries retained in the rolling deque
_MAX_ENTRIES: int = 10_000
# Top-N sources reported in the summary
_TOP_SOURCES_N: int = 10


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(tz=timezone.utc)


class StatsEngine:
    """Maintains rolling statistics over a configurable time window.

    All internal collections are bounded to prevent unbounded memory
    growth. Level and source counts are fully rebuilt from scratch after
    each cleanup pass, guaranteeing accuracy without stale counters.
    """

    def __init__(self, window_minutes: int = 5) -> None:
        """Initialise the engine.

        Args:
            window_minutes: Width of the rolling time window in minutes.
        """
        self._window_minutes = window_minutes
        self._window_delta = timedelta(minutes=window_minutes)

        # Rolling entry store — bounded by both size and time
        self._entries: deque[LogEntry] = deque(maxlen=_MAX_ENTRIES)

        # Rebuilt on every _cleanup_old() call; never accumulate stale keys
        self._level_counts: defaultdict[str, int] = defaultdict(int)
        self._source_counts: defaultdict[str, int] = defaultdict(int)

        # Error timestamps for errors-per-minute rate (time-bounded only)
        self._error_timestamps: deque[datetime] = deque()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add(self, entry: LogEntry) -> None:
        """Ingest a LogEntry and update rolling state.

        Calls _cleanup_old() on every invocation so memory stays bounded
        at all times rather than only during periodic sweeps.

        Args:
            entry: The parsed log entry to ingest.
        """
        self._entries.append(entry)
        if entry.level in (LogLevel.ERROR, LogLevel.CRITICAL):
            self._error_timestamps.append(entry.timestamp)
        self._cleanup_old()

    def error_rate(self) -> float:
        """Return the number of errors in the last 60 seconds.

        Returns:
            A float count of ERROR/CRITICAL entries within the past minute.
        """
        cutoff = _utcnow() - timedelta(seconds=60)
        return sum(
            1 for ts in self._error_timestamps
            if ts.replace(tzinfo=timezone.utc) >= cutoff
            if ts.tzinfo is None
            or ts >= cutoff
        )

    def get_summary(self) -> StatsSummary:
        """Build and return a StatsSummary snapshot of current state.

        Returns:
            A fully populated StatsSummary reflecting the current window.
        """
        top_sources = sorted(
            self._source_counts.items(), key=lambda kv: kv[1], reverse=True
        )[:_TOP_SOURCES_N]
        return StatsSummary(
            total_entries=len(self._entries),
            error_rate_rpm=self.error_rate(),
            level_breakdown=dict(self._level_counts),
            top_sources=top_sources,
            window_minutes=self._window_minutes,
            captured_at=_utcnow(),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _cleanup_old(self) -> None:
        """Remove entries outside the rolling window and rebuild counters.

        Removes stale entries from both _entries and _error_timestamps,
        then rebuilds _level_counts and _source_counts from scratch.
        This approach guarantees that counters never contain stale keys,
        preventing unbounded growth even when sources or levels disappear.
        """
        cutoff = _utcnow() - self._window_delta

        # Purge expired error timestamps (left side of deque is oldest)
        while self._error_timestamps:
            ts = self._error_timestamps[0]
            effective_ts = (
                ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            )
            if effective_ts < cutoff:
                self._error_timestamps.popleft()
            else:
                break

        # Evict old entries from the left (oldest) end
        while self._entries:
            entry = self._entries[0]
            ets = entry.timestamp
            effective_ets = (
                ets if ets.tzinfo else ets.replace(tzinfo=timezone.utc)
            )
            if effective_ets < cutoff:
                self._entries.popleft()
            else:
                break

        # Rebuild derived counters entirely from the surviving entries
        new_level: defaultdict[str, int] = defaultdict(int)
        new_source: defaultdict[str, int] = defaultdict(int)
        for e in self._entries:
            new_level[e.level.value] += 1
            new_source[e.source] += 1
        self._level_counts = new_level
        self._source_counts = new_source
