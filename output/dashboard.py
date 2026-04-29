"""Rich terminal dashboard for the Smart Log Analyzer.

Renders a live multi-panel layout showing statistics, level breakdown,
top sources, matched patterns, and recent alerts.  The ``render`` method
is a pure function; side effects are limited to ``add_alert``.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone

from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text

from core.models import AlertEvent, StatsSummary

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------
_MAX_ALERTS: int = 100
_DISPLAY_ALERTS: int = 8
_ERROR_RATE_GREEN: float = 5.0
_ERROR_RATE_YELLOW: float = 10.0
_APP_NAME = "🔍 Smart Log Analyzer"


def _utcnow() -> datetime:
    """Return the current UTC time."""
    return datetime.now(tz=timezone.utc)


def _rate_colour(rate: float) -> str:
    """Return a Rich colour string based on the error rate.

    Args:
        rate: Current error rate in errors per minute.

    Returns:
        A Rich markup colour name.
    """
    if rate < _ERROR_RATE_GREEN:
        return "green"
    if rate < _ERROR_RATE_YELLOW:
        return "yellow"
    return "red"


class Dashboard:
    """Rich Live terminal dashboard.

    ``add_alert`` is the only mutating operation; ``render`` is a pure
    function that returns a Layout without side effects.
    """

    def __init__(self) -> None:
        """Initialise the dashboard with an empty alert history."""
        self._alerts: deque[AlertEvent] = deque(maxlen=_MAX_ALERTS)
        self._lock = threading.Lock()
        self._active_patterns: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_alert(self, event: AlertEvent) -> None:
        """Prepend an alert event to the internal history.

        Args:
            event: The alert event to store.
        """
        with self._lock:
            self._alerts.appendleft(event)

    def set_patterns(self, patterns: list[str]) -> None:
        """Update the active patterns shown in the patterns panel.

        Args:
            patterns: List of currently matched pattern names.
        """
        with self._lock:
            self._active_patterns = list(patterns)

    def render(self, summary: StatsSummary) -> Layout:
        """Build and return a Rich Layout snapshot.

        This is a pure function w.r.t. the summary argument; the only
        implicit reads are of ``_alerts`` and ``_active_patterns``.

        Args:
            summary: The latest statistics snapshot.

        Returns:
            A fully populated Rich Layout ready for display.
        """
        with self._lock:
            alerts_snapshot = list(self._alerts)[:_DISPLAY_ALERTS]
            patterns_snapshot = list(self._active_patterns)

        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="alerts", size=12),
        )
        layout["body"].split_row(
            Layout(name="stats", ratio=1),
            Layout(name="levels", ratio=1),
            Layout(name="sources", ratio=1),
            Layout(name="patterns", ratio=1),
        )

        layout["header"].update(self._make_header())
        layout["body"]["stats"].update(self._make_stats_panel(summary))
        layout["body"]["levels"].update(
            self._make_levels_panel(summary)
        )
        layout["body"]["sources"].update(
            self._make_sources_panel(summary)
        )
        layout["body"]["patterns"].update(
            self._make_patterns_panel(patterns_snapshot)
        )
        layout["alerts"].update(
            self._make_alerts_panel(alerts_snapshot)
        )
        return layout

    # ------------------------------------------------------------------
    # Private panel builders
    # ------------------------------------------------------------------

    @staticmethod
    def _make_header() -> Panel:
        """Build the header panel with app name and current time."""
        now = _utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        text = Text(justify="center")
        text.append(_APP_NAME + "  ", style="bold cyan")
        text.append(now, style="dim")
        return Panel(text, style="bold blue")

    @staticmethod
    def _make_stats_panel(summary: StatsSummary) -> Panel:
        """Build the statistics overview panel.

        Args:
            summary: The current statistics snapshot.

        Returns:
            A Rich Panel displaying key metrics.
        """
        colour = _rate_colour(summary.error_rate_rpm)
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()
        table.add_row("Total entries:", str(summary.total_entries))
        table.add_row(
            "Error rate:",
            Text(
                f"{summary.error_rate_rpm:.1f}/min",
                style=colour,
            ),
        )
        table.add_row("Window:", f"{summary.window_minutes} min")
        table.add_row(
            "Snapshot:",
            summary.captured_at.strftime("%H:%M:%S"),
        )
        return Panel(table, title="📊 Statistics", border_style="blue")

    @staticmethod
    def _make_levels_panel(summary: StatsSummary) -> Panel:
        """Build the log level breakdown panel with bar indicators.

        Args:
            summary: The current statistics snapshot.

        Returns:
            A Rich Panel with a bar for each log level.
        """
        progress = Progress(
            TextColumn("[bold]{task.description}"),
            BarColumn(bar_width=18),
            TextColumn("{task.completed}"),
        )
        level_colours = {
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold red",
        }
        total = max(summary.total_entries, 1)
        for level, count in summary.level_breakdown.items():
            colour = level_colours.get(level, "white")
            progress.add_task(
                f"[{colour}]{level:<8}",
                total=total,
                completed=count,
            )
        return Panel(
            progress, title="📈 Level Breakdown", border_style="green"
        )

    @staticmethod
    def _make_sources_panel(summary: StatsSummary) -> Panel:
        """Build the top sources table panel.

        Args:
            summary: The current statistics snapshot.

        Returns:
            A Rich Panel with a table of the top sources.
        """
        table = Table(
            "Source", "Count", show_header=True, header_style="bold magenta"
        )
        for source, count in summary.top_sources[:8]:
            table.add_row(source[:30], str(count))
        return Panel(
            table, title="🌐 Top Sources", border_style="magenta"
        )

    @staticmethod
    def _make_patterns_panel(patterns: list[str]) -> Panel:
        """Build the active patterns panel.

        Args:
            patterns: Currently matched pattern names.

        Returns:
            A Rich Panel listing active patterns.
        """
        if not patterns:
            content: Text | str = Text("No patterns active", style="dim")
        else:
            content = Text("\n".join(f"• {p}" for p in patterns))
        return Panel(
            content, title="🔎 Active Patterns", border_style="yellow"
        )

    @staticmethod
    def _make_alerts_panel(alerts: list[AlertEvent]) -> Panel:
        """Build the recent alerts panel.

        Args:
            alerts: Up to 8 most recent alert events.

        Returns:
            A Rich Panel with a table of alert events.
        """
        table = Table(
            "Time",
            "Severity",
            "Rule",
            "Detail",
            show_header=True,
            header_style="bold red",
        )
        severity_styles = {
            "critical": "bold red",
            "warning": "bold yellow",
        }
        for event in alerts:
            style = severity_styles.get(event.severity, "white")
            table.add_row(
                event.timestamp.strftime("%H:%M:%S"),
                Text(event.severity.upper(), style=style),
                event.rule_name,
                event.message[:60],
            )
        return Panel(table, title="🚨 Recent Alerts", border_style="red")
