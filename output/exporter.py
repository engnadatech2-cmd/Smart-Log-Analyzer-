"""JSON and CSV exporters for log entries and statistics summaries.

All writers are synchronous and are expected to be called from the main
thread or a dedicated export thread.  No global state is used.
"""
from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime

from core.models import LogEntry, StatsSummary

logger = logging.getLogger(__name__)


def _serialize_entry(entry: LogEntry) -> dict:
    """Convert a LogEntry to a JSON-serialisable dict.

    Args:
        entry: The log entry to serialise.

    Returns:
        A plain dict with ISO 8601 timestamp and level as string.
    """
    return {
        "timestamp": entry.timestamp.isoformat(),
        "level": entry.level.value,
        "source": entry.source,
        "message": entry.message,
    }


class Exporter:
    """Exports log entries and statistics to JSON and CSV files.

    All methods accept an explicit file path so the caller controls
    directory layout and file naming without any module-level state.
    """

    def export_json(
        self, entries: list[LogEntry], filepath: str
    ) -> None:
        """Write *entries* as newline-delimited JSON to *filepath*.

        Each line is a self-contained JSON object (JSON Lines format),
        making the output streamable and easy to process with tools like
        ``jq``.

        Args:
            entries:  Log entries to export.
            filepath: Destination file path (created if absent).
        """
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                for entry in entries:
                    fh.write(json.dumps(_serialize_entry(entry)) + "\n")
            logger.info("Exported %d entries to %s", len(entries), filepath)
        except OSError as exc:
            logger.error("JSON export failed: %s", exc)

    def export_csv(
        self, entries: list[LogEntry], filepath: str
    ) -> None:
        """Write *entries* as a CSV file with a header row to *filepath*.

        Columns: timestamp, level, source, message.

        Args:
            entries:  Log entries to export.
            filepath: Destination file path (created if absent).
        """
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        fieldnames = ["timestamp", "level", "source", "message"]
        try:
            with open(
                filepath, "w", newline="", encoding="utf-8"
            ) as fh:
                writer = csv.DictWriter(fh, fieldnames=fieldnames)
                writer.writeheader()
                for entry in entries:
                    writer.writerow(_serialize_entry(entry))
            logger.info("Exported %d entries to %s", len(entries), filepath)
        except OSError as exc:
            logger.error("CSV export failed: %s", exc)

    def export_summary(
        self, summary: StatsSummary, filepath: str
    ) -> None:
        """Write a pretty-printed JSON snapshot of *summary* to *filepath*.

        Args:
            summary:  The statistics summary to serialise.
            filepath: Destination file path (created if absent).
        """
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        data = {
            "total_entries": summary.total_entries,
            "error_rate_rpm": summary.error_rate_rpm,
            "level_breakdown": summary.level_breakdown,
            "top_sources": summary.top_sources,
            "window_minutes": summary.window_minutes,
            "captured_at": summary.captured_at.isoformat(),
        }
        try:
            with open(filepath, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            logger.info("Exported summary to %s", filepath)
        except OSError as exc:
            logger.error("Summary export failed: %s", exc)
