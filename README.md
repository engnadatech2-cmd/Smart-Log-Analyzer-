# Smart Log Analyzer & Alerting System

A **production-quality, real-time log monitoring system** written in Python 3.11+.
It tails a log file, parses every line into structured data, computes rolling
statistics, detects anomalies via Z-score analysis, fires configurable alerts,
and displays a live Rich terminal dashboard — all while exposing a REST API.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py  (pipeline)                       │
│                                                                   │
│  ┌──────────────┐   raw line   ┌─────────────┐   LogEntry       │
│  │ LogFileWatcher│ ──────────► │  LogParser  │ ──────────────►  │
│  │  (daemon thd) │             │  (4 formats)│     queue.Queue  │
│  └──────────────┘             └─────────────┘         │        │
│                                                        ▼        │
│  ┌──────────────┐    summary   ┌─────────────────────────────┐  │
│  │  AlertEngine │ ◄────────── │   StatsEngine  (main thread) │  │
│  │  (cooldown)  │             │   AnomalyDetector            │  │
│  └──────┬───────┘             │   PatternMatcher             │  │
│         │ AlertEvent          └─────────────────────────────┘  │
│    ┌────▼──────────────────────────────┐                        │
│    │  Notifier (Console / Slack / HTTP) │                        │
│    │  Dashboard.add_alert()             │                        │
│    │  AppState.add_alert()  (API)       │                        │
│    └───────────────────────────────────┘                        │
│                                                                   │
│  ┌─────────────────────┐   ┌──────────────────────────────────┐ │
│  │  Rich Live Dashboard│   │  FastAPI  /stats /alerts /health  │ │
│  │  (main thread)      │   │  (uvicorn daemon thread)          │ │
│  └─────────────────────┘   └──────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/you/smart-log-analyzer.git
cd smart-log-analyzer

# 2. Create and activate a virtual environment (Python 3.11+)
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Usage

### Point it at a log file

Edit `config.yaml` and set the `log_file` path:

```yaml
log_file: "C:/logs/myapp.log"   # Windows
# log_file: "/var/log/app.log"  # Linux / macOS
```

Then run:

```bash
python main.py
# Or specify a custom config:
python main.py --config /path/to/myconfig.yaml
```

The **Rich dashboard** fills your terminal automatically.  
The **REST API** starts at `http://localhost:8000`.

---

## Adding a New Alert Rule

Open `config.yaml` and add an entry under `alert_rules`:

```yaml
alert_rules:
  - name: "Critical Error Spike"
    metric: "error_rate_rpm"   # key from StatsSummary
    threshold: 20.0            # fires when metric > threshold
    severity: "critical"       # "warning" | "critical"
    cooldown_s: 30             # min seconds between repeated firings
```

Available metrics: `error_rate_rpm`, `total_entries`, `window_minutes`.

---

## Enabling Slack Notifications

In `config.yaml`:

```yaml
notifications:
  console: true
  slack:
    enabled: true
    webhook_url: "https://hooks.slack.com/services/T.../B.../xxxx"
```

Alerts are posted asynchronously in daemon threads; a broken webhook
never crashes the main process.

---

## REST API

The API starts on `http://0.0.0.0:8000` by default.

### `GET /stats` — Current statistics snapshot

```bash
curl http://localhost:8000/stats
```

```json
{
  "total_entries": 1234,
  "error_rate_rpm": 3.2,
  "level_breakdown": {"INFO": 900, "ERROR": 45, "WARNING": 289},
  "top_sources": [["database", 400], ["auth", 300]],
  "window_minutes": 5,
  "captured_at": "2024-01-15T14:23:01+00:00"
}
```

Returns **422** if the analyzer is still warming up.

### `GET /alerts?limit=50` — Recent alerts

```bash
curl "http://localhost:8000/alerts?limit=10"
```

```json
{
  "alerts": [
    {
      "rule_name": "High Error Rate",
      "severity": "critical",
      "message": "error_rate_rpm = 12.00 (threshold: 10.0)",
      "value": 12.0,
      "threshold": 10.0,
      "timestamp": "2024-01-15T14:25:00+00:00"
    }
  ],
  "total": 1
}
```

### `GET /health` — Health check

```bash
curl http://localhost:8000/health
```

```json
{"status": "ok", "uptime_s": 42.1, "version": "1.0.0"}
```

---

## Running Tests

```bash
# Run all tests with verbose output
pytest tests/ -v

# Run a specific module
pytest tests/test_parser.py -v

# Run with coverage (install pytest-cov first)
pip install pytest-cov
pytest tests/ -v --cov=. --cov-report=term-missing
```

---

## Project Structure

```
smart-log-analyzer/
├── main.py                     # Pipeline entry point
├── config.yaml                 # Fully documented configuration
├── requirements.txt
│
├── core/
│   ├── models.py               # Frozen dataclasses: LogEntry, AlertEvent, StatsSummary
│   ├── buffer.py               # Thread-safe generic circular buffer
│   ├── parser.py               # 4-format regex parser (standard/Apache/syslog/JSON)
│   └── watcher.py              # tail -f with rotation detection + backoff
│
├── analysis/
│   ├── stats_engine.py         # Bounded rolling-window statistics
│   ├── anomaly_detector.py     # Z-score anomaly detection
│   └── pattern_matcher.py      # Named regex pattern library
│
├── alerts/
│   ├── alert_rules.py          # AlertRule dataclass + config loader
│   ├── alert_engine.py         # Rule evaluation + per-rule cooldown
│   └── notifier.py             # Console / Slack / HTTP notification backends
│
├── output/
│   ├── api.py                  # FastAPI app with AppState (Lock-protected)
│   ├── dashboard.py            # Rich Live multi-panel terminal dashboard
│   └── exporter.py             # JSON Lines + CSV export
│
└── tests/
    ├── conftest.py
    ├── test_parser.py
    ├── test_stats_engine.py
    ├── test_anomaly_detector.py
    ├── test_alert_engine.py
    └── test_watcher.py
```

---

## CV-Ready Bullet Points

- **Engineered a real-time log monitoring system** in Python 3.11+ using
  a thread-safe producer/consumer pipeline (`queue.Queue`, `threading.Lock`)
  capable of processing high-velocity log streams without data races.

- **Implemented Z-score anomaly detection** over a bounded sliding-window
  baseline, automatically flagging statistical outliers in error rates with
  configurable sensitivity thresholds.

- **Designed a multi-format log parser** supporting standard, Apache Combined,
  syslog, and JSON Lines formats via compiled regex patterns, with graceful
  degradation and rate-limited warnings for unrecognised input.

- **Built a REST API** with FastAPI and an `AppState` dataclass (protected by
  `threading.Lock`) exposing live metrics, alert history, and health endpoints
  consumed by external monitoring systems.

- **Delivered a live terminal dashboard** using Rich `Live` + `Layout`, with
  colour-coded error rates, log level progress bars, top-source tables, and
  a real-time alert feed updating at 2 Hz.

- **Achieved zero memory leaks** by bounding all internal data structures with
  `deque(maxlen=N)` and rebuilding derived counters from scratch on every
  cleanup pass, preventing unbounded growth in long-running deployments.

- **Implemented log rotation detection** by comparing OS inode numbers and
  file sizes on every poll cycle, transparently re-opening the file from
  byte 0 with exponential back-off retry on absence.

- **Delivered non-blocking alerting** via Slack and generic HTTP webhooks
  dispatched in daemon threads, with full exception isolation so a broken
  notification backend never disrupts the main analysis pipeline.
