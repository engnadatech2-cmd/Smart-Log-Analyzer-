"""Multi-format log line parser.

Tries four named regex patterns in order and returns a typed LogEntry
on first match, or None if every pattern fails.  Unparsed lines are
rate-limited to one Python logging warning per minute.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime

from core.models import LogEntry, LogLevel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled regex patterns
# ---------------------------------------------------------------------------

# Standard: "2024-01-15 14:23:01 ERROR database Connection timeout"
_RE_STANDARD = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
    r"(?P<source>\S+)\s+"
    r"(?P<message>.+)$"
)

# Apache Combined:
# 127.0.0.1 - - [15/Jan/2024:14:23:01 +0000] "GET /api HTTP/1.1" 500 1234
_RE_APACHE = re.compile(
    r'^(?P<host>\S+) \S+ \S+ \[(?P<timestamp>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S+) \S+" '
    r"(?P<status>\d{3}) (?P<bytes>\d+)"
)

# Syslog: "Jan 15 14:23:01 hostname appname[1234]: message body"
_RE_SYSLOG = re.compile(
    r"^(?P<timestamp>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+"
    r"(?P<source>\w+)(?:\[\d+\])?:\s+"
    r"(?P<message>.+)$"
)

# JSON line: {"ts": "...", "level": "...", "msg": "...", "src": "..."}
_RE_JSON_DETECT = re.compile(r"^\s*\{")

# ---------------------------------------------------------------------------
# Timestamp format strings
# ---------------------------------------------------------------------------
_FMT_STANDARD = "%Y-%m-%d %H:%M:%S"
_FMT_APACHE = "%d/%b/%Y:%H:%M:%S %z"
_FMT_SYSLOG = "%b %d %H:%M:%S"

# Rate-limiting state for unparsed-line warnings
_WARN_INTERVAL_S: float = 60.0
_last_warn_ts: float = 0.0


def _http_status_to_level(status: int) -> LogLevel:
    """Map an HTTP status code to a LogLevel.

    Args:
        status: The integer HTTP status code.

    Returns:
        The corresponding LogLevel.
    """
    match status // 100:
        case 2:
            return LogLevel.INFO
        case 3:
            return LogLevel.DEBUG
        case 4:
            return LogLevel.WARNING
        case _:
            return LogLevel.ERROR


def _coerce_level(raw: str) -> LogLevel:
    """Convert a raw level string to a LogLevel, defaulting to INFO.

    Args:
        raw: The level string extracted from the log line.

    Returns:
        The matching LogLevel member, or INFO on unrecognised input.
    """
    try:
        return LogLevel[raw.upper()]
    except KeyError:
        return LogLevel.INFO


def _parse_standard(raw: str) -> LogEntry | None:
    """Attempt to parse *raw* as a standard-format log line.

    Returns:
        A LogEntry on success, None on failure.
    """
    m = _RE_STANDARD.match(raw)
    if not m:
        return None
    try:
        ts = datetime.strptime(m.group("timestamp"), _FMT_STANDARD)
    except ValueError:
        return None
    return LogEntry(
        timestamp=ts,
        level=_coerce_level(m.group("level")),
        source=m.group("source"),
        message=m.group("message"),
        raw=raw,
    )


def _parse_apache(raw: str) -> LogEntry | None:
    """Attempt to parse *raw* as an Apache Combined Log Format line.

    Returns:
        A LogEntry on success, None on failure.
    """
    m = _RE_APACHE.match(raw)
    if not m:
        return None
    try:
        ts = datetime.strptime(m.group("timestamp"), _FMT_APACHE)
    except ValueError:
        return None
    status = int(m.group("status"))
    level = _http_status_to_level(status)
    message = (
        f'{m.group("method")} {m.group("path")} → {status}'
    )
    return LogEntry(
        timestamp=ts,
        level=level,
        source=m.group("host"),
        message=message,
        raw=raw,
    )


def _parse_syslog(raw: str) -> LogEntry | None:
    """Attempt to parse *raw* as a syslog-format line.

    Returns:
        A LogEntry on success, None on failure.
    """
    m = _RE_SYSLOG.match(raw)
    if not m:
        return None
    raw_ts = m.group("timestamp")
    current_year = datetime.now().year
    try:
        ts = datetime.strptime(
            f"{current_year} {raw_ts}", f"%Y {_FMT_SYSLOG}"
        )
    except ValueError:
        return None
    return LogEntry(
        timestamp=ts,
        level=LogLevel.INFO,
        source=m.group("source"),
        message=m.group("message"),
        raw=raw,
    )


def _parse_json(raw: str) -> LogEntry | None:
    """Attempt to parse *raw* as a newline-delimited JSON log line.

    Expected keys: "ts", "level", "msg", "src".

    Returns:
        A LogEntry on success, None on failure.
    """
    if not _RE_JSON_DETECT.match(raw):
        return None
    try:
        data = json.loads(raw)
        ts_str: str = data["ts"]
        # Accept ISO 8601 with or without fractional seconds
        ts_str = ts_str.replace("Z", "+00:00")
        ts = datetime.fromisoformat(ts_str)
        return LogEntry(
            timestamp=ts,
            level=_coerce_level(data.get("level", "INFO")),
            source=str(data.get("src", "unknown")),
            message=str(data.get("msg", "")),
            raw=raw,
        )
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


class LogParser:
    """Multi-format log line parser.

    Tries patterns in priority order: standard → Apache → syslog → JSON.
    Returns None only when all patterns fail.  Rate-limited warnings are
    emitted for unparsed lines (at most once per minute).
    """

    def __init__(self) -> None:
        """Initialise the parser with the pre-compiled pattern set."""
        self._parsers = [
            _parse_standard,
            _parse_apache,
            _parse_syslog,
            _parse_json,
        ]

    def parse(self, raw_line: str) -> LogEntry | None:
        """Parse a single raw log line into a LogEntry.

        Args:
            raw_line: The raw text of one log line (no trailing newline
                      required, but acceptable).

        Returns:
            A LogEntry on success, or None if all patterns fail.
        """
        line = raw_line.rstrip("\n\r")
        if not line:
            return None

        for fn in self._parsers:
            entry = fn(line)
            if entry is not None:
                return entry

        self._maybe_warn(line)
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _maybe_warn(line: str) -> None:
        """Emit a rate-limited warning for an unparsed log line.

        Warnings are suppressed if one was already emitted within the
        last minute to prevent log flooding.
        """
        global _last_warn_ts  # noqa: PLW0603
        now = time.monotonic()
        if now - _last_warn_ts >= _WARN_INTERVAL_S:
            logger.warning("Unparsed log line: %r", line[:120])
            _last_warn_ts = now
