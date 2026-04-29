"""Tests for the Z-score anomaly detector."""
from __future__ import annotations

import pytest

from analysis.anomaly_detector import AnomalyDetector


class TestMinimumReadings:
    """Detector must not fire before accumulating enough data."""

    def test_needs_ten_readings_before_detecting(self) -> None:
        """Fewer than 10 readings must always return None."""
        det = AnomalyDetector(window_size=60, threshold_z=2.0)
        for i in range(9):
            result = det.add_reading(float(i))
            assert result is None, f"Expected None on reading {i + 1}"


class TestAnomalyDetection:
    """Detector must flag genuine statistical outliers."""

    def test_spike_detected_above_threshold(self) -> None:
        """A reading far above the mean must return a non-None Z-score."""
        det = AnomalyDetector(window_size=60, threshold_z=2.0)
        # Establish a stable baseline with slight natural variation so std > 0
        for i in range(20):
            det.add_reading(0.9 if i % 2 == 0 else 1.1)
        # Inject a massive spike — Z-score will be enormous
        z = det.add_reading(1000.0)
        assert z is not None
        assert abs(z) > 2.0

    def test_normal_reading_returns_none(self) -> None:
        """A reading within the normal range must return None."""
        det = AnomalyDetector(window_size=60, threshold_z=3.0)
        # Establish baseline
        for _ in range(20):
            det.add_reading(5.0)
        # A reading very close to the mean should not be flagged
        z = det.add_reading(5.1)
        assert z is None


class TestReset:
    """reset() must clear all history."""

    def test_reset_clears_history(self) -> None:
        """After reset(), the detector must behave as if freshly created."""
        det = AnomalyDetector(window_size=60, threshold_z=2.0)
        for _ in range(20):
            det.add_reading(1.0)
        det.reset()
        # After reset fewer than 10 readings → should not detect
        for i in range(9):
            result = det.add_reading(1000.0)
            assert result is None, f"Expected None after reset on reading {i + 1}"


class TestIsSpikeMethod:
    """is_spike() must use a multiplicative threshold."""

    def test_is_spike_true_when_multiplied(self) -> None:
        """is_spike must return True when current > mean * multiplier."""
        det = AnomalyDetector(window_size=60, threshold_z=3.0)
        for _ in range(10):
            det.add_reading(1.0)
        assert det.is_spike(current=100.0, multiplier=3.0) is True

    def test_is_spike_false_when_within_range(self) -> None:
        """is_spike must return False for a reading near the mean."""
        det = AnomalyDetector(window_size=60, threshold_z=3.0)
        for _ in range(10):
            det.add_reading(5.0)
        assert det.is_spike(current=5.5, multiplier=3.0) is False

    def test_is_spike_false_with_too_few_readings(self) -> None:
        """is_spike must return False when fewer than 5 readings exist."""
        det = AnomalyDetector(window_size=60, threshold_z=3.0)
        for _ in range(4):
            det.add_reading(1.0)
        assert det.is_spike(current=999.0, multiplier=3.0) is False
