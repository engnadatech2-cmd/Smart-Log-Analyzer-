"""Named regex pattern library for log message classification.

Provides a curated set of compiled patterns covering common failure
modes found in production log streams.
"""
from __future__ import annotations

import re

from core.models import LogEntry

# ---------------------------------------------------------------------------
# Named pattern library
# ---------------------------------------------------------------------------
PATTERNS: dict[str, re.Pattern[str]] = {
    "oom_killer": re.compile(
        r"Out of memory|oom.killer", re.IGNORECASE
    ),
    "disk_full": re.compile(
        r"No space left on device", re.IGNORECASE
    ),
    "connection_refused": re.compile(
        r"Connection refused", re.IGNORECASE
    ),
    "timeout": re.compile(
        r"(timed? ?out|timeout)", re.IGNORECASE
    ),
    "segfault": re.compile(
        r"segmentation fault|SIGSEGV", re.IGNORECASE
    ),
    "auth_failure": re.compile(
        r"(authentication failed|invalid password|401)", re.IGNORECASE
    ),
    "stack_overflow": re.compile(
        r"(stack overflow|RecursionError)", re.IGNORECASE
    ),
}


class PatternMatcher:
    """Matches log entry messages against the named pattern library.

    Returns all pattern names whose regex matches the entry's message,
    enabling downstream components to attach semantic labels to raw log
    lines without recompiling patterns on every call.
    """

    def __init__(
        self,
        patterns: dict[str, re.Pattern[str]] | None = None,
    ) -> None:
        """Initialise the matcher.

        Args:
            patterns: Optional custom pattern mapping.  Defaults to the
                      built-in PATTERNS library when not supplied.
        """
        self._patterns = patterns if patterns is not None else PATTERNS

    def match(self, entry: LogEntry) -> list[str]:
        """Return the names of all patterns that match *entry.message*.

        Args:
            entry: The log entry whose message field will be tested.

        Returns:
            A list of matched pattern names (may be empty).
        """
        return [
            name
            for name, pattern in self._patterns.items()
            if pattern.search(entry.message)
        ]
