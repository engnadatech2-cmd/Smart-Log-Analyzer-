"""Shared pytest fixtures for the Smart Log Analyzer test suite."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from core.models import LogEntry, LogLevel

# ---------------------------------------------------------------------------
# Sample log lines covering all four formats
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_log_lines() -> list[str]:
    """Return ten realistic log lines spanning all four supported formats."""
    return [
        # Standard (×3)
        "2024-01-15 14:23:01 ERROR database Connection timeout after 30s",
        "2024-01-15 14:23:02 INFO  auth User admin logged in successfully",
        "2024-01-15 14:23:03 WARNING scheduler Job queue depth exceeded 100",
        # Apache Combined (×3)
        '192.168.1.10 - alice [15/Jan/2024:14:23:04 +0000] "GET /api/v1/users HTTP/1.1" 200 512',
        '10.0.0.5 - - [15/Jan/2024:14:23:05 +0000] "POST /api/v1/login HTTP/1.1" 401 128',
        '172.16.0.2 - bob [15/Jan/2024:14:23:06 +0000] "DELETE /api/v1/item/9 HTTP/1.1" 500 64',
        # Syslog (×2)
        "Jan 15 14:23:07 webserver nginx[1234]: connection refused from 203.0.113.1",
        "Jan 15 14:23:08 dbhost postgres[5678]: authentication failed for user root",
        # JSON Lines (×2)
        '{"ts": "2024-01-15T14:23:09", "level": "ERROR", "msg": "Out of memory: kill process", "src": "kernel"}',
        '{"ts": "2024-01-15T14:23:10", "level": "INFO",  "msg": "Service started", "src": "app"}',
    ]


@pytest.fixture()
def tmp_log_file(tmp_path):
    """Return the path to a temporary empty log file."""
    p = tmp_path / "test_app.log"
    p.write_text("")
    return str(p)


@pytest.fixture()
def sample_config() -> dict:
    """Return a minimal valid application configuration dict."""
    return {
        "log_file": "/var/log/app.log",
        "watcher": {"poll_interval_ms": 100, "retry_backoff_max_s": 30},
        "stats": {"window_minutes": 5, "max_entries": 10000},
        "anomaly": {"window_size": 60, "threshold_z": 3.0},
        "api": {"host": "127.0.0.1", "port": 8000},
        "dashboard": {"refresh_per_second": 2},
        "alert_rules": [
            {
                "name": "High Error Rate",
                "metric": "error_rate_rpm",
                "threshold": 10.0,
                "severity": "critical",
                "cooldown_s": 60,
            }
        ],
        "notifications": {"console": False},
        "export": {
            "enabled": False,
            "output_dir": "./exports",
            "format": "json",
            "interval_minutes": 10,
        },
    }


def make_entry(
    level: LogLevel = LogLevel.INFO,
    source: str = "test",
    message: str = "test message",
    ts: datetime | None = None,
) -> LogEntry:
    """Construct a simple LogEntry for use in tests.

    Args:
        level:   Log level (default INFO).
        source:  Source identifier (default "test").
        message: Log message body.
        ts:      Timestamp (default current UTC time).

    Returns:
        A frozen LogEntry instance.
    """
    if ts is None:
        ts = datetime.now(tz=timezone.utc)
    return LogEntry(
        timestamp=ts,
        level=level,
        source=source,
        message=message,
        raw=f"{ts} {level.value} {source} {message}",
    )
