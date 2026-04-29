"""Tests for the multi-format log line parser."""
from __future__ import annotations

import pytest

from core.models import LogLevel
from core.parser import LogParser


@pytest.fixture()
def parser() -> LogParser:
    """Return a fresh LogParser instance."""
    return LogParser()


class TestStandardFormat:
    """Tests for the standard timestamp/level/source/message format."""

    def test_parse_standard_format(self, parser: LogParser) -> None:
        """A well-formed standard line must produce a valid LogEntry."""
        line = "2024-01-15 14:23:01 ERROR database Connection timeout"
        entry = parser.parse(line)
        assert entry is not None
        assert entry.level == LogLevel.ERROR
        assert entry.source == "database"
        assert "Connection timeout" in entry.message
        assert entry.timestamp.year == 2024

    def test_parse_standard_info(self, parser: LogParser) -> None:
        """Standard INFO line must parse correctly."""
        line = "2024-06-01 09:00:00 INFO app Service started"
        entry = parser.parse(line)
        assert entry is not None
        assert entry.level == LogLevel.INFO

    def test_parse_standard_critical(self, parser: LogParser) -> None:
        """Standard CRITICAL line must map to LogLevel.CRITICAL."""
        line = "2024-06-01 09:00:00 CRITICAL core Fatal error occurred"
        entry = parser.parse(line)
        assert entry is not None
        assert entry.level == LogLevel.CRITICAL


class TestApacheFormat:
    """Tests for Apache Combined Log Format parsing."""

    def test_parse_apache_format(self, parser: LogParser) -> None:
        """A well-formed Apache line must produce a valid LogEntry."""
        line = (
            '127.0.0.1 - - [15/Jan/2024:14:23:01 +0000] '
            '"GET /api HTTP/1.1" 200 1234'
        )
        entry = parser.parse(line)
        assert entry is not None
        assert entry.source == "127.0.0.1"
        assert entry.timestamp.year == 2024

    def test_apache_2xx_maps_to_info(self, parser: LogParser) -> None:
        """HTTP 200 must map to LogLevel.INFO."""
        line = (
            '10.0.0.1 - - [15/Jan/2024:12:00:00 +0000] '
            '"GET /health HTTP/1.1" 200 0'
        )
        entry = parser.parse(line)
        assert entry is not None
        assert entry.level == LogLevel.INFO

    def test_apache_3xx_maps_to_debug(self, parser: LogParser) -> None:
        """HTTP 302 must map to LogLevel.DEBUG."""
        line = (
            '10.0.0.1 - - [15/Jan/2024:12:00:00 +0000] '
            '"GET /old HTTP/1.1" 302 0'
        )
        entry = parser.parse(line)
        assert entry is not None
        assert entry.level == LogLevel.DEBUG

    def test_apache_4xx_maps_to_warning(self, parser: LogParser) -> None:
        """HTTP 404 must map to LogLevel.WARNING."""
        line = (
            '10.0.0.1 - - [15/Jan/2024:12:00:00 +0000] '
            '"GET /missing HTTP/1.1" 404 0'
        )
        entry = parser.parse(line)
        assert entry is not None
        assert entry.level == LogLevel.WARNING

    def test_apache_5xx_maps_to_error(self, parser: LogParser) -> None:
        """HTTP 500 must map to LogLevel.ERROR."""
        line = (
            '127.0.0.1 - - [15/Jan/2024:14:23:01 +0000] '
            '"POST /api HTTP/1.1" 500 1234'
        )
        entry = parser.parse(line)
        assert entry is not None
        assert entry.level == LogLevel.ERROR


class TestSyslogFormat:
    """Tests for syslog-format parsing."""

    def test_parse_syslog_format(self, parser: LogParser) -> None:
        """A well-formed syslog line must produce a valid LogEntry."""
        line = "Jan 15 14:23:01 hostname nginx[1234]: connection refused"
        entry = parser.parse(line)
        assert entry is not None
        assert entry.source == "nginx"
        assert "connection refused" in entry.message

    def test_parse_syslog_without_pid(self, parser: LogParser) -> None:
        """Syslog lines without a PID bracket must still parse."""
        line = "Jan 15 14:23:01 hostname sshd: Accepted publickey for root"
        entry = parser.parse(line)
        assert entry is not None
        assert entry.source == "sshd"


class TestJsonFormat:
    """Tests for JSON Lines format parsing."""

    def test_parse_json_format(self, parser: LogParser) -> None:
        """A valid JSON log line must produce a correct LogEntry."""
        line = (
            '{"ts": "2024-01-15T14:23:01", "level": "ERROR", '
            '"msg": "Disk full", "src": "kernel"}'
        )
        entry = parser.parse(line)
        assert entry is not None
        assert entry.level == LogLevel.ERROR
        assert entry.source == "kernel"
        assert "Disk full" in entry.message

    def test_parse_json_missing_key_returns_none(
        self, parser: LogParser
    ) -> None:
        """A JSON line missing the required 'ts' key must return None."""
        line = '{"level": "INFO", "msg": "no timestamp", "src": "app"}'
        entry = parser.parse(line)
        assert entry is None

    def test_parse_json_invalid_json_returns_none(
        self, parser: LogParser
    ) -> None:
        """Malformed JSON must return None without raising."""
        line = '{"ts": "2024-01-15T14:23:01", "level": "INFO"'  # truncated
        entry = parser.parse(line)
        assert entry is None


class TestUnknownFormat:
    """Tests for lines that do not match any known format."""

    def test_parse_unknown_returns_none(self, parser: LogParser) -> None:
        """A line matching no pattern must return None."""
        line = "THIS IS NOT A VALID LOG LINE AT ALL"
        entry = parser.parse(line)
        assert entry is None

    def test_parse_empty_returns_none(self, parser: LogParser) -> None:
        """An empty string must return None without error."""
        entry = parser.parse("")
        assert entry is None

    def test_parse_whitespace_returns_none(self, parser: LogParser) -> None:
        """A whitespace-only string must return None."""
        entry = parser.parse("   \n  ")
        assert entry is None
