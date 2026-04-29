"""FastAPI REST API for the Smart Log Analyzer.

Exposes /stats, /alerts, and /health endpoints.  All shared mutable
state is encapsulated in AppState, protected by a threading.Lock, so
the uvicorn server thread and the main analysis thread never race.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from core.models import AlertEvent, StatsSummary

# ---------------------------------------------------------------------------
# Application state — no module-level mutable dicts
# ---------------------------------------------------------------------------
_APP_VERSION = "1.0.0"
_APP_START_TIME = time.monotonic()
_ALERTS_MAXLEN = 200


@dataclass
class AppState:
    """Thread-safe container for all shared API state.

    All public methods acquire the internal lock so that FastAPI route
    handlers (uvicorn thread) and the analysis loop (main thread) can
    safely read and write concurrently.
    """

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stats: StatsSummary | None = field(default=None)
    _alerts: deque[dict] = field(
        default_factory=lambda: deque(maxlen=_ALERTS_MAXLEN)
    )

    def update_stats(self, summary: StatsSummary) -> None:
        """Replace the stored statistics snapshot.

        Args:
            summary: The latest StatsSummary from StatsEngine.
        """
        with self._lock:
            self._stats = summary

    def add_alert(self, event: AlertEvent) -> None:
        """Append a serialised AlertEvent to the alerts ring-buffer.

        Args:
            event: The alert event to store.
        """
        payload = {
            "rule_name": event.rule_name,
            "severity": event.severity,
            "message": event.message,
            "value": event.value,
            "threshold": event.threshold,
            "timestamp": event.timestamp.isoformat(),
        }
        with self._lock:
            self._alerts.appendleft(payload)

    def get_stats(self) -> StatsSummary | None:
        """Return the most recent StatsSummary snapshot, or None.

        Returns:
            The current StatsSummary, or None if no data has arrived yet.
        """
        with self._lock:
            return self._stats

    def get_alerts(self, limit: int) -> list[dict]:
        """Return the *limit* most recent alerts.

        Args:
            limit: Maximum number of alerts to return.

        Returns:
            A list of alert dicts, newest first.
        """
        with self._lock:
            return list(self._alerts)[:limit]

    def total_alerts(self) -> int:
        """Return the total number of stored alerts.

        Returns:
            Integer count of alerts currently in the buffer.
        """
        with self._lock:
            return len(self._alerts)


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Smart Log Analyzer",
    version=_APP_VERSION,
    description="Real-time log monitoring REST API.",
)
state = AppState()


@app.get("/stats", summary="Get current statistics snapshot")
def get_stats() -> dict:
    """Return the most recent rolling statistics summary.

    Raises:
        HTTPException 422: If no statistics have been computed yet.
    """
    summary = state.get_stats()
    if summary is None:
        raise HTTPException(
            status_code=422,
            detail="Statistics not yet available — analyzer is warming up.",
        )
    return {
        "total_entries": summary.total_entries,
        "error_rate_rpm": summary.error_rate_rpm,
        "level_breakdown": summary.level_breakdown,
        "top_sources": summary.top_sources,
        "window_minutes": summary.window_minutes,
        "captured_at": summary.captured_at.isoformat(),
    }


@app.get("/alerts", summary="Get recent alert events")
def get_alerts(limit: int = 50) -> dict:
    """Return the most recent alert events.

    Args:
        limit: Maximum number of alerts to return (default 50, max 200).
    """
    effective_limit = min(max(limit, 1), _ALERTS_MAXLEN)
    alerts = state.get_alerts(effective_limit)
    return {"alerts": alerts, "total": state.total_alerts()}


@app.get("/health", summary="Health check")
def health() -> dict:
    """Return service health and uptime.

    Returns:
        A dict with status, uptime_s, and version.
    """
    return {
        "status": "ok",
        "uptime_s": round(time.monotonic() - _APP_START_TIME, 2),
        "version": _APP_VERSION,
    }
