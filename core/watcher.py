"""Log file watcher with rotation detection.

Uses polling to tail a log file, detecting both inode changes and file
shrinkage (both are indicators of log rotation) and re-opening the file
from byte 0 in those cases.  Exponential back-off is applied when the
file is absent.
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------
DEFAULT_POLL_INTERVAL_S: float = 0.1
BACKOFF_BASE_S: float = 0.5
BACKOFF_MAX_S: float = 30.0
READ_CHUNK_BYTES: int = 65_536  # 64 KiB per read


class LogFileWatcher:
    """Tail a log file and invoke a callback for every new line.

    Handles log rotation by checking both the inode number and the
    reported file size on every poll.  When either changes unexpectedly
    (inode differs or size decreases) the file is considered rotated and
    re-opened from byte 0.

    The watcher is intentionally simple: it runs a blocking polling loop
    and is expected to be launched in a dedicated daemon thread.
    """

    def __init__(
        self,
        filepath: str,
        callback: Callable[[str], None],
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        """Initialise the watcher.

        Args:
            filepath:        Absolute or relative path to the log file.
            callback:        Invoked with each new raw log line (stripped
                             of the trailing newline).
            poll_interval_s: Seconds to sleep between polls (default 0.1).
        """
        self._filepath = filepath
        self._callback = callback
        self._poll_interval_s = poll_interval_s
        self._running = False
        self._last_inode: int | None = None
        self._last_size: int = 0
        self._rotated: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Block and tail the log file, calling *callback* for each line.

        On ``KeyboardInterrupt`` the loop exits cleanly.  When the target
        file is absent, exponential back-off is applied up to
        ``BACKOFF_MAX_S`` seconds between retries.
        """
        self._running = True
        fh = None
        backoff = BACKOFF_BASE_S

        try:
            while self._running:
                # ---- ensure file is open --------------------------------
                if fh is None:
                    seek_end = not self._rotated
                    fh = self._open_with_backoff(backoff, seek_end=seek_end)
                    if fh is None:
                        backoff = min(backoff * 2, BACKOFF_MAX_S)
                        continue
                    backoff = BACKOFF_BASE_S  # reset after success
                    self._rotated = False
                    stat = os.stat(self._filepath)
                    self._last_inode = stat.st_ino
                    self._last_size = stat.st_size

                # ---- rotation check ------------------------------------
                rotated = self._detect_rotation()
                if rotated:
                    logger.warning(
                        "Log rotation detected for %s — re-opening.",
                        self._filepath,
                    )
                    fh.close()
                    fh = None
                    self._rotated = True
                    continue

                # ---- read new data -------------------------------------
                for line in fh:
                    stripped = line.rstrip("\n\r")
                    if stripped:
                        self._callback(stripped)

                time.sleep(self._poll_interval_s)

        except KeyboardInterrupt:
            logger.info("LogFileWatcher interrupted.")
        finally:
            if fh is not None:
                fh.close()
            self._running = False

    def stop(self) -> None:
        """Signal the polling loop to exit after the current iteration."""
        self._running = False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _open_with_backoff(self, backoff: float, *, seek_end: bool = True):  # type: ignore[return]
        """Try to open the log file, sleeping *backoff* seconds on failure.

        Args:
            backoff: Seconds to sleep when the file is not found.

        Returns:
            An open file handle, or None if the file was not found.
        """
        try:
            fh = open(self._filepath, "r", encoding="utf-8", errors="replace")
            if seek_end:
                fh.seek(0, 2)  # tail mode: skip existing content on first open
            else:
                fh.seek(0)    # rotation mode: read from byte 0
            logger.info("Opened log file: %s", self._filepath)
            return fh
        except FileNotFoundError:
            logger.warning(
                "Log file not found: %s — retrying in %.1fs",
                self._filepath,
                backoff,
            )
            time.sleep(backoff)
            return None

    def _detect_rotation(self) -> bool:
        """Check whether the log file has been rotated.

        Returns:
            True if the inode changed or the file shrank (rotation
            indicators), False otherwise or when stat fails.
        """
        try:
            stat = os.stat(self._filepath)
        except FileNotFoundError:
            return True  # file vanished — treat as rotation

        inode_changed = (
            self._last_inode is not None
            and stat.st_ino != self._last_inode
        )
        size_decreased = stat.st_size < self._last_size

        if not inode_changed and not size_decreased:
            self._last_size = stat.st_size
            self._last_inode = stat.st_ino
            return False

        self._last_inode = stat.st_ino
        self._last_size = stat.st_size
        return True
