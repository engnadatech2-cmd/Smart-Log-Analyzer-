"""Z-score anomaly detector for streaming numeric readings.

Maintains a bounded history of readings and flags values that deviate
from the rolling mean by more than a configurable number of standard
deviations.
"""
from __future__ import annotations

import logging
import math
from collections import deque

logger = logging.getLogger(__name__)

# Minimum readings before Z-score computation is meaningful
_MIN_READINGS: int = 10
# Minimum readings before spike detection activates
_MIN_SPIKE_READINGS: int = 5
# Small epsilon added to std to prevent division-by-zero on a constant baseline
_EPSILON: float = 1e-9


class AnomalyDetector:
    """Z-score anomaly detector for a stream of numeric readings.

    Readings are appended to a bounded history *after* computing the
    Z-score so that each new value is compared against a baseline that
    does not include itself, avoiding bias toward self-confirmation.
    """

    def __init__(
        self,
        window_size: int = 60,
        threshold_z: float = 3.0,
    ) -> None:
        """Initialise the detector.

        Args:
            window_size: Maximum number of historical readings retained.
            threshold_z: Z-score magnitude above which an anomaly is
                         reported.
        """
        self._window_size = window_size
        self._threshold_z = threshold_z
        self._history: deque[float] = deque(maxlen=window_size)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_reading(self, value: float) -> float | None:
        """Ingest a new reading and optionally return its Z-score.

        The value is appended to history only *after* computing the
        Z-score against the existing baseline.

        Args:
            value: The new numeric measurement (e.g. error_rate_rpm).

        Returns:
            The Z-score if its absolute value exceeds *threshold_z*,
            otherwise None.  Returns None when fewer than 10 readings
            have been collected.
        """
        if len(self._history) < _MIN_READINGS:
            self._history.append(value)
            return None

        mean, std = self._stats()
        if std == 0.0:
            # Baseline is perfectly constant — insufficient variance to compute
            # a meaningful Z-score.  Append and skip detection this cycle.
            self._history.append(value)
            return None

        z = (value - mean) / std
        self._history.append(value)

        if abs(z) > self._threshold_z:
            logger.debug("Anomaly detected: value=%.2f z=%.2f", value, z)
            return z
        return None

    def is_spike(self, current: float, multiplier: float = 3.0) -> bool:
        """Determine whether *current* constitutes a multiplicative spike.

        Args:
            current:    The value to test.
            multiplier: Required multiple of the mean to count as a spike.

        Returns:
            True if current > mean * multiplier and at least 5 readings
            exist, False otherwise.
        """
        if len(self._history) < _MIN_SPIKE_READINGS:
            return False
        mean, _ = self._stats()
        return current > mean * multiplier

    def reset(self) -> None:
        """Clear the reading history.

        Should be called when the monitored log file is rotated so that
        stale baseline values do not corrupt new readings.
        """
        self._history.clear()
        logger.info("AnomalyDetector history reset.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _stats(self) -> tuple[float, float]:
        """Compute the mean and population standard deviation of history.

        Returns:
            A (mean, std) tuple.  std is 0.0 when all values are equal.
        """
        data = list(self._history)
        n = len(data)
        mean = sum(data) / n
        variance = sum((x - mean) ** 2 for x in data) / n
        return mean, math.sqrt(variance)
