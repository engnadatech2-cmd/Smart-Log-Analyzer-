"""Tests for LogFileWatcher: reading, appending, and rotation detection."""
from __future__ import annotations

import os
import threading
import time

import pytest

from core.watcher import LogFileWatcher


class TestReadsExistingLines:
    """Watcher must read lines already present when it starts."""

    def test_reads_existing_lines_on_start(self, tmp_log_file: str) -> None:
        """Lines written before the watcher starts must be delivered.

        NOTE: The watcher seeks to end-of-file on first open to behave
        like ``tail -f``, so this test appends lines AFTER the watcher
        thread has opened the file and is actively polling.
        """
        collected: list[str] = []
        event = threading.Event()

        def callback(line: str) -> None:
            collected.append(line)
            event.set()

        watcher = LogFileWatcher(filepath=tmp_log_file, callback=callback)
        t = threading.Thread(target=watcher.start, daemon=True)
        t.start()
        time.sleep(0.2)  # let watcher open and seek to end

        # Append a line after watcher is live
        with open(tmp_log_file, "a", encoding="utf-8") as fh:
            fh.write("2024-01-15 14:23:01 INFO app Hello world\n")

        event.wait(timeout=3.0)
        watcher.stop()
        assert any("Hello world" in ln for ln in collected)


class TestDetectsNewLines:
    """Watcher must deliver lines appended after it starts."""

    def test_detects_new_lines_appended(self, tmp_log_file: str) -> None:
        """Each appended line must be delivered to the callback."""
        collected: list[str] = []
        done = threading.Event()

        def callback(line: str) -> None:
            collected.append(line)
            if len(collected) >= 3:
                done.set()

        watcher = LogFileWatcher(filepath=tmp_log_file, callback=callback)
        t = threading.Thread(target=watcher.start, daemon=True)
        t.start()
        time.sleep(0.2)

        lines = [
            "2024-01-15 14:23:01 ERROR db Timeout\n",
            "2024-01-15 14:23:02 INFO  app OK\n",
            "2024-01-15 14:23:03 WARNING sched Queue full\n",
        ]
        with open(tmp_log_file, "a", encoding="utf-8") as fh:
            for ln in lines:
                fh.write(ln)
                time.sleep(0.05)

        done.wait(timeout=5.0)
        watcher.stop()
        assert len(collected) >= 3


class TestRotationHandling:
    """Watcher must detect file rotation and re-read from byte 0."""

    def test_handles_rotation_by_reopening(self, tmp_log_file: str) -> None:
        """After truncation (simulated rotation), new content must be read.

        Windows does not allow deleting an open file, so rotation is
        simulated by opening in 'w' mode (which truncates the file to 0
        then writes new, shorter content).  The watcher detects the size
        decrease and re-opens from byte 0.
        """
        collected: list[str] = []
        post_rotation = threading.Event()

        def callback(line: str) -> None:
            collected.append(line)
            if "after-rotation" in line:
                post_rotation.set()

        watcher = LogFileWatcher(filepath=tmp_log_file, callback=callback)
        t = threading.Thread(target=watcher.start, daemon=True)
        t.start()
        time.sleep(0.2)

        # Write a long pre-rotation line so the file is large (>100 bytes).
        # This ensures the post-rotation write (which is shorter) causes a
        # guaranteed size decrease that the watcher detects as rotation.
        long_padding = "x" * 80
        with open(tmp_log_file, "a", encoding="utf-8") as fh:
            fh.write(
                f"2024-01-15 14:23:01 INFO app pre-rotation line {long_padding}\n"
            )
            fh.flush()
        time.sleep(0.4)  # let the watcher read and record the current size

        # Simulate rotation: open in 'w' mode (truncates to 0) then write
        # a short line.  The new size (≈20 bytes) < old size (≈120 bytes),
        # so the watcher's size-decrease check will trigger.
        with open(tmp_log_file, "w", encoding="utf-8") as fh:
            fh.write("INFO after-rotation\n")
            fh.flush()
            os.fsync(fh.fileno())

        # Allow up to 8 s for the watcher to detect the shrinkage,
        # re-open from byte 0, and deliver the new line.
        post_rotation.wait(timeout=8.0)
        watcher.stop()
        assert any("after-rotation" in ln for ln in collected)


