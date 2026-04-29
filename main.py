"""Smart Log Analyzer — main entry point.

Wires all components together into a thread-safe pipeline:

  Watcher thread  →  queue.Queue  →  Main analysis loop  →  Rich Live dashboard
                                                          →  FastAPI (uvicorn thread)
                                                          →  Exporter

Usage:
    python main.py [--config config.yaml]
"""
from __future__ import annotations

import argparse
import logging
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone

import uvicorn
import yaml
from rich.live import Live

from alerts.alert_engine import AlertEngine
from alerts.alert_rules import load_rules_from_config
from alerts.notifier import Notifier
from analysis.anomaly_detector import AnomalyDetector
from analysis.pattern_matcher import PatternMatcher
from analysis.stats_engine import StatsEngine
from core.models import AlertEvent, LogEntry
from core.parser import LogParser
from core.watcher import LogFileWatcher
from output.api import app as fastapi_app
from output.api import state as api_state
from output.dashboard import Dashboard
from output.exporter import Exporter

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_CONFIG_PATH = "config.yaml"
DASHBOARD_REFRESH_S: float = 0.5
QUEUE_TIMEOUT_S: float = 0.1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_config(path: str) -> dict:
    """Load and return the YAML configuration file.

    Args:
        path: Path to the YAML config file.

    Returns:
        Parsed configuration dictionary.

    Exits with code 1 if the file is missing or malformed.
    """
    if not os.path.exists(path):
        print(
            f"[ERROR] Configuration file not found: {path}\n"
            "  Create a config.yaml or pass --config <path>.",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            config = yaml.safe_load(fh)
        logger.info("Loaded configuration from %s", path)
        return config
    except yaml.YAMLError as exc:
        print(f"[ERROR] Failed to parse {path}: {exc}", file=sys.stderr)
        sys.exit(1)


def _start_api_thread(host: str, port: int) -> threading.Thread:
    """Start uvicorn in a daemon thread.

    Args:
        host: Bind host (e.g. "0.0.0.0").
        port: Bind port.

    Returns:
        The started daemon thread.
    """
    def _run() -> None:
        uvicorn.run(
            fastapi_app,
            host=host,
            port=port,
            log_level="warning",
        )

    t = threading.Thread(target=_run, daemon=True, name="uvicorn")
    t.start()
    logger.info("FastAPI started on http://%s:%d", host, port)
    return t


def _start_watcher_thread(
    filepath: str,
    entry_queue: queue.Queue[LogEntry],
    parser: LogParser,
) -> tuple[LogFileWatcher, threading.Thread]:
    """Start the log file watcher in a daemon thread.

    Args:
        filepath:    Path to the log file to tail.
        entry_queue: Queue to push parsed entries into.
        parser:      LogParser instance.

    Returns:
        A (watcher, thread) tuple.
    """
    def _callback(raw_line: str) -> None:
        entry = parser.parse(raw_line)
        if entry is not None:
            entry_queue.put(entry)

    watcher = LogFileWatcher(filepath=filepath, callback=_callback)
    t = threading.Thread(
        target=watcher.start, daemon=True, name="watcher"
    )
    t.start()
    logger.info("Watcher thread started for %s", filepath)
    return watcher, t


def _fire_anomaly_alert(
    z_score: float,
    rate: float,
    alert_engine: AlertEngine,
) -> None:
    """Synthesise and dispatch an anomaly alert.

    Args:
        z_score:      The Z-score that triggered the anomaly.
        rate:         The current error rate reading.
        alert_engine: Engine to dispatch the alert through.
    """
    from core.models import AlertEvent  # local to avoid circular-import risk

    event = AlertEvent(
        rule_name="Anomaly Detected",
        severity="critical",
        message=(
            f"Error rate anomaly: {rate:.2f}/min "
            f"(Z-score={z_score:.2f})"
        ),
        value=rate,
        threshold=0.0,
        timestamp=datetime.now(tz=timezone.utc),
    )
    for cb in alert_engine._callbacks:  # noqa: SLF001
        try:
            cb(event)
        except Exception as exc:  # noqa: BLE001
            logger.error("Anomaly alert callback error: %s", exc)


def _export_if_due(
    last_export_time: float,
    interval_s: float,
    entries_snapshot: list[LogEntry],
    exporter: Exporter,
    output_dir: str,
    fmt: str,
) -> float:
    """Export entries if the configured interval has elapsed.

    Args:
        last_export_time: monotonic timestamp of the last export.
        interval_s:       Export interval in seconds.
        entries_snapshot: Current list of entries to export.
        exporter:         Exporter instance.
        output_dir:       Directory for output files.
        fmt:              "json" or "csv".

    Returns:
        Updated last_export_time (unchanged if export did not run).
    """
    now = time.monotonic()
    if now - last_export_time < interval_s:
        return last_export_time

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(output_dir, exist_ok=True)
    if fmt == "csv":
        path = os.path.join(output_dir, f"entries_{ts}.csv")
        exporter.export_csv(entries_snapshot, path)
    else:
        path = os.path.join(output_dir, f"entries_{ts}.json")
        exporter.export_json(entries_snapshot, path)
    return now


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point: parse args, build pipeline, run analysis loop."""
    parser_cli = argparse.ArgumentParser(
        description="Smart Log Analyzer & Alerting System"
    )
    parser_cli.add_argument(
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to YAML config file (default: {DEFAULT_CONFIG_PATH})",
    )
    args = parser_cli.parse_args()

    # ── 1. Load configuration ─────────────────────────────────────────────
    config = _load_config(args.config)

    log_file_path: str = config.get("log_file", "/var/log/app.log")
    watcher_cfg: dict = config.get("watcher", {})
    stats_cfg: dict = config.get("stats", {})
    anomaly_cfg: dict = config.get("anomaly", {})
    api_cfg: dict = config.get("api", {})
    dashboard_cfg: dict = config.get("dashboard", {})
    export_cfg: dict = config.get("export", {})

    poll_interval_s = watcher_cfg.get("poll_interval_ms", 100) / 1000.0
    window_minutes: int = stats_cfg.get("window_minutes", 5)
    anomaly_window: int = anomaly_cfg.get("window_size", 60)
    anomaly_z: float = float(anomaly_cfg.get("threshold_z", 3.0))
    api_host: str = api_cfg.get("host", "0.0.0.0")
    api_port: int = int(api_cfg.get("port", 8000))
    dashboard_rps: int = dashboard_cfg.get("refresh_per_second", 2)
    export_enabled: bool = export_cfg.get("enabled", False)
    export_dir: str = export_cfg.get("output_dir", "./exports")
    export_fmt: str = export_cfg.get("format", "json")
    export_interval_s: float = (
        float(export_cfg.get("interval_minutes", 10)) * 60
    )

    # ── 2. Build components ───────────────────────────────────────────────
    log_parser = LogParser()
    stats_engine = StatsEngine(window_minutes=window_minutes)
    anomaly_detector = AnomalyDetector(
        window_size=anomaly_window, threshold_z=anomaly_z
    )
    pattern_matcher = PatternMatcher()
    rules = load_rules_from_config(config)
    alert_engine = AlertEngine(rules=rules)
    notifier = Notifier.from_config(config)
    dashboard = Dashboard()
    exporter = Exporter()

    # ── 3. Inter-thread queue ─────────────────────────────────────────────
    entry_queue: queue.Queue[LogEntry] = queue.Queue()

    # ── 4. Register alert callbacks ───────────────────────────────────────
    alert_engine.on_alert(notifier.notify)
    alert_engine.on_alert(dashboard.add_alert)
    alert_engine.on_alert(api_state.add_alert)

    # ── 5. Start FastAPI ──────────────────────────────────────────────────
    _start_api_thread(api_host, api_port)

    # ── 6. Start watcher ──────────────────────────────────────────────────
    watcher, watcher_thread = _start_watcher_thread(
        filepath=log_file_path,
        entry_queue=entry_queue,
        parser=log_parser,
    )

    # ── 7. Main consumer loop ─────────────────────────────────────────────
    last_export_time = time.monotonic()
    last_dashboard_time = time.monotonic()
    all_entries: list[LogEntry] = []  # for export; cleared on each export

    logger.info("Analysis loop starting. Press Ctrl+C to stop.")

    with Live(
        dashboard.render(
            stats_engine.get_summary()
        ),
        refresh_per_second=dashboard_rps,
        screen=True,
    ) as live:
        try:
            while True:
                # Drain queue entries
                try:
                    entry = entry_queue.get(timeout=QUEUE_TIMEOUT_S)
                    stats_engine.add(entry)
                    all_entries.append(entry)

                    patterns = pattern_matcher.match(entry)
                    if patterns:
                        dashboard.set_patterns(patterns)

                    summary = stats_engine.get_summary()
                    z = anomaly_detector.add_reading(
                        summary.error_rate_rpm
                    )
                    if z is not None:
                        _fire_anomaly_alert(z, summary.error_rate_rpm, alert_engine)

                    alert_engine.evaluate(summary)
                    api_state.update_stats(summary)

                    if export_enabled:
                        last_export_time = _export_if_due(
                            last_export_time,
                            export_interval_s,
                            list(all_entries),
                            exporter,
                            export_dir,
                            export_fmt,
                        )
                        # Clear after export to avoid accumulation
                        if time.monotonic() - last_export_time < 1.0:
                            all_entries.clear()

                except queue.Empty:
                    pass

                # Refresh dashboard every 0.5 s regardless of queue activity
                now = time.monotonic()
                if now - last_dashboard_time >= DASHBOARD_REFRESH_S:
                    summary = stats_engine.get_summary()
                    live.update(dashboard.render(summary))
                    last_dashboard_time = now

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received — shutting down.")

    # ── 8. Graceful shutdown ──────────────────────────────────────────────
    watcher.stop()

    # Flush remaining queue items
    flushed = 0
    while not entry_queue.empty():
        try:
            entry = entry_queue.get_nowait()
            stats_engine.add(entry)
            all_entries.append(entry)
            flushed += 1
        except queue.Empty:
            break
    if flushed:
        logger.info("Flushed %d remaining queue items.", flushed)

    # Final export
    if export_enabled and all_entries:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(export_dir, exist_ok=True)
        final_path = os.path.join(
            export_dir,
            f"final_{ts}.{export_fmt}",
        )
        if export_fmt == "csv":
            exporter.export_csv(all_entries, final_path)
        else:
            exporter.export_json(all_entries, final_path)

    print("Analyzer stopped.")
    sys.exit(0)


if __name__ == "__main__":
    main()
