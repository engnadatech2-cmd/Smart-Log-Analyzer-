"""Notification backends for the Smart Log Analyzer.

Provides ConsoleNotifier, SlackNotifier, WebhookNotifier, and an
orchestrating Notifier class that fans out to all configured backends.
All network operations are non-blocking (daemon threads) and swallow
exceptions so that a broken notifier never crashes the main pipeline.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import asdict

import requests
from rich.console import Console

from core.models import AlertEvent

logger = logging.getLogger(__name__)

_rich_console = Console(highlight=False)

# Colour palette for severity levels
_SEVERITY_COLOURS: dict[str, str] = {
    "critical": "bold red",
    "warning": "bold yellow",
}


class ConsoleNotifier:
    """Print alert events to the terminal using Rich styled output."""

    def notify(self, event: AlertEvent) -> None:
        """Print a coloured alert banner to the console.

        Args:
            event: The alert event to display.
        """
        colour = _SEVERITY_COLOURS.get(event.severity, "white")
        ts = event.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        _rich_console.print(
            f"[{colour}]⚠  ALERT [{event.severity.upper()}] "
            f"{event.rule_name}[/{colour}]  "
            f"— {event.message}  ({ts})"
        )


class SlackNotifier:
    """Post alert events to a Slack incoming webhook URL.

    Network requests run in daemon threads and all exceptions are
    swallowed to prevent notification failures from affecting the
    main pipeline.
    """

    def __init__(self, webhook_url: str) -> None:
        """Initialise with a Slack incoming webhook URL.

        Args:
            webhook_url: The full HTTPS URL of the Slack incoming webhook.
        """
        self._webhook_url = webhook_url

    def notify(self, event: AlertEvent) -> None:
        """Post an alert event to Slack in a background daemon thread.

        Args:
            event: The alert event to post.
        """
        t = threading.Thread(
            target=self._post, args=(event,), daemon=True
        )
        t.start()

    def _post(self, event: AlertEvent) -> None:
        """Perform the blocking HTTP POST to the Slack webhook.

        Args:
            event: The alert event payload.
        """
        colour = "danger" if event.severity == "critical" else "warning"
        payload = {
            "attachments": [
                {
                    "color": colour,
                    "title": f"⚠ {event.rule_name}",
                    "text": event.message,
                    "fields": [
                        {
                            "title": "Severity",
                            "value": event.severity.upper(),
                            "short": True,
                        },
                        {
                            "title": "Value",
                            "value": f"{event.value:.2f}",
                            "short": True,
                        },
                    ],
                    "ts": event.timestamp.timestamp(),
                }
            ]
        }
        try:
            resp = requests.post(
                self._webhook_url, json=payload, timeout=5
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Slack notification failed (suppressed): %s", exc)


class WebhookNotifier:
    """POST alert events as JSON to a configurable HTTP endpoint.

    Network requests run in daemon threads and all exceptions are
    swallowed to prevent notification failures from affecting the
    main pipeline.
    """

    def __init__(
        self, url: str, headers: dict[str, str] | None = None
    ) -> None:
        """Initialise with a target URL and optional custom headers.

        Args:
            url:     The HTTP(S) endpoint to POST to.
            headers: Optional extra HTTP headers (e.g. ``Authorization``).
        """
        self._url = url
        self._headers = headers or {}

    def notify(self, event: AlertEvent) -> None:
        """POST the alert event JSON in a background daemon thread.

        Args:
            event: The alert event to post.
        """
        t = threading.Thread(
            target=self._post, args=(event,), daemon=True
        )
        t.start()

    def _post(self, event: AlertEvent) -> None:
        """Perform the blocking HTTP POST to the configured URL.

        Args:
            event: The alert event payload.
        """
        payload = {
            "rule_name": event.rule_name,
            "severity": event.severity,
            "message": event.message,
            "value": event.value,
            "threshold": event.threshold,
            "timestamp": event.timestamp.isoformat(),
        }
        try:
            resp = requests.post(
                self._url,
                json=payload,
                headers=self._headers,
                timeout=5,
            )
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Webhook notification failed (suppressed): %s", exc)


class Notifier:
    """Orchestrates multiple notification backends.

    Fans out each alert event to every registered backend.  Use
    ``from_config`` to build an instance from the application config dict.
    """

    def __init__(
        self,
        backends: list[ConsoleNotifier | SlackNotifier | WebhookNotifier],
    ) -> None:
        """Initialise with a list of notification backends.

        Args:
            backends: One or more backend instances to fan out to.
        """
        self._backends = backends

    def notify(self, event: AlertEvent) -> None:
        """Dispatch *event* to all registered backends.

        Args:
            event: The alert event to dispatch.
        """
        for backend in self._backends:
            try:
                backend.notify(event)
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "Notifier backend %s raised (suppressed): %s",
                    type(backend).__name__,
                    exc,
                )

    @classmethod
    def from_config(cls, config: dict) -> "Notifier":
        """Build a Notifier from the ``notifications`` section of config.

        Args:
            config: The top-level application configuration dictionary.

        Returns:
            A fully configured Notifier instance.
        """
        notif_cfg = config.get("notifications", {})
        backends: list[ConsoleNotifier | SlackNotifier | WebhookNotifier] = []

        if notif_cfg.get("console", True):
            backends.append(ConsoleNotifier())

        slack_cfg = notif_cfg.get("slack", {})
        if slack_cfg.get("enabled", False):
            url = slack_cfg.get("webhook_url", "")
            if url:
                backends.append(SlackNotifier(webhook_url=url))
            else:
                logger.warning("Slack enabled but webhook_url is empty.")

        webhook_cfg = notif_cfg.get("webhook", {})
        if webhook_cfg.get("enabled", False):
            url = webhook_cfg.get("url", "")
            if url:
                backends.append(
                    WebhookNotifier(
                        url=url,
                        headers=webhook_cfg.get("headers", {}),
                    )
                )
            else:
                logger.warning("Webhook notifier enabled but url is empty.")

        if not backends:
            logger.warning(
                "No notification backends configured — alerts will be silent."
            )
        return cls(backends)
