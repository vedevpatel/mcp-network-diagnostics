"""Unit tests for trend analysis math."""
import pytest
from mcp_network.trends.store import MetricSeries
from mcp_network.trends.analyzer import (
    compute_rate,
    compute_acceleration,
    estimate_time_to_threshold,
    analyze_trend,
)


class TestComputeRate:
    def test_constant_metric_zero_rate(self):
        s = MetricSeries(max_samples=20)
        for i in range(10):
            s.add(50.0, timestamp=i * 60.0)
        assert compute_rate(s.samples) == pytest.approx(0.0, abs=0.01)

    def test_linear_increase(self):
        s = MetricSeries(max_samples=20)
        for i in range(10):
            s.add(50.0 + i, timestamp=i * 60.0)  # +1 unit/min
        assert compute_rate(s.samples) == pytest.approx(1.0, abs=0.01)

    def test_linear_decrease(self):
        s = MetricSeries(max_samples=20)
        for i in range(10):
            s.add(80.0 - 2 * i, timestamp=i * 60.0)  # -2 units/min
        assert compute_rate(s.samples) == pytest.approx(-2.0, abs=0.01)

    def test_single_sample_returns_zero(self):
        s = MetricSeries(max_samples=20)
        s.add(50.0, timestamp=0.0)
        assert compute_rate(s.samples) == 0.0

    def test_zero_time_span_returns_zero(self):
        s = MetricSeries(max_samples=20)
        s.add(50.0, timestamp=0.0)
        s.add(60.0, timestamp=0.0)
        assert compute_rate(s.samples) == 0.0

    def test_empty_samples_returns_zero(self):
        assert compute_rate([]) == 0.0

    def test_noisy_but_trending(self):
        """OLS should still detect the trend through noise."""
        s = MetricSeries(max_samples=20)
        # True rate is +1/min, with ±2 noise
        import random
        random.seed(99)
        for i in range(20):
            s.add(50.0 + i + random.uniform(-2, 2), timestamp=i * 60.0)
        rate = compute_rate(s.samples)
        assert 0.5 < rate < 1.5  # roughly correct despite noise


class TestComputeAcceleration:
    def test_constant_rate_zero_acceleration(self):
        s = MetricSeries(max_samples=20)
        for i in range(10):
            s.add(50.0 + i, timestamp=i * 60.0)
        assert compute_acceleration(s.samples) == pytest.approx(0.0, abs=0.05)

    def test_accelerating_metric(self):
        s = MetricSeries(max_samples=20)
        for i in range(10):
            s.add(float(i * i), timestamp=i * 60.0)  # quadratic
        assert compute_acceleration(s.samples) > 0

    def test_decelerating_metric(self):
        s = MetricSeries(max_samples=20)
        # Fast rise then slow rise
        for i in range(5):
            s.add(float(i * 4), timestamp=i * 60.0)
        for i in range(5, 10):
            s.add(20.0 + (i - 5) * 0.5, timestamp=i * 60.0)
        assert compute_acceleration(s.samples) < 0

    def test_fewer_than_four_returns_zero(self):
        s = MetricSeries(max_samples=20)
        for i in range(3):
            s.add(float(i), timestamp=i * 60.0)
        assert compute_acceleration(s.samples) == 0.0


class TestEstimateTimeToThreshold:
    def test_basic_estimate(self):
        # At 70, rising 2/min, threshold 80 => 5 minutes
        assert estimate_time_to_threshold(70.0, 2.0, 80.0) == pytest.approx(5.0)

    def test_already_breached(self):
        assert estimate_time_to_threshold(85.0, 2.0, 80.0) == 0.0

    def test_exactly_at_threshold(self):
        assert estimate_time_to_threshold(80.0, 2.0, 80.0) == 0.0

    def test_falling_returns_none(self):
        assert estimate_time_to_threshold(70.0, -1.0, 80.0) is None

    def test_zero_rate_returns_none(self):
        assert estimate_time_to_threshold(70.0, 0.0, 80.0) is None

    def test_slow_approach(self):
        # At 79, rising 0.1/min, threshold 80 => 10 minutes
        assert estimate_time_to_threshold(79.0, 0.1, 80.0) == pytest.approx(10.0)


class TestAnalyzeTrend:
    def test_rising_toward_threshold(self):
        s = MetricSeries(max_samples=20)
        for i in range(10):
            s.add(70.0 + i, timestamp=i * 60.0)  # +1/min from 70
        result = analyze_trend(s, "cpu", threshold=80.0, horizon_minutes=15.0)
        assert result is not None
        assert result.direction == "rising"
        assert result.will_breach is True
        assert result.time_to_threshold_minutes is not None

    def test_stable_no_breach(self):
        s = MetricSeries(max_samples=20)
        for i in range(10):
            s.add(50.0, timestamp=i * 60.0)
        result = analyze_trend(s, "cpu", threshold=80.0, horizon_minutes=5.0)
        assert result.direction == "stable"
        assert result.will_breach is False

    def test_falling_no_breach(self):
        s = MetricSeries(max_samples=20)
        for i in range(10):
            s.add(70.0 - i, timestamp=i * 60.0)  # falling from 70 toward 61
        result = analyze_trend(s, "cpu", threshold=80.0, horizon_minutes=5.0)
        assert result.direction == "falling"
        assert result.will_breach is False

    def test_breach_outside_horizon(self):
        s = MetricSeries(max_samples=20)
        for i in range(10):
            s.add(70.0 + 0.5 * i, timestamp=i * 60.0)  # +0.5/min, needs 20 min
        result = analyze_trend(s, "cpu", threshold=80.0, horizon_minutes=5.0)
        assert result.direction == "rising"
        assert result.will_breach is False
        assert result.time_to_threshold_minutes is not None
        assert result.time_to_threshold_minutes > 5.0

    def test_single_sample_returns_none(self):
        s = MetricSeries(max_samples=20)
        s.add(50.0, timestamp=0.0)
        assert analyze_trend(s, "cpu", threshold=80.0) is None

    def test_confidence_low(self):
        s = MetricSeries(max_samples=20)
        for i in range(3):
            s.add(50.0 + i, timestamp=i * 60.0)
        result = analyze_trend(s, "cpu", threshold=80.0)
        assert result.confidence == "low"

    def test_confidence_medium(self):
        s = MetricSeries(max_samples=20)
        for i in range(8):
            s.add(50.0 + i, timestamp=i * 60.0)
        result = analyze_trend(s, "cpu", threshold=80.0)
        assert result.confidence == "medium"

    def test_confidence_high(self):
        s = MetricSeries(max_samples=20)
        for i in range(18):
            s.add(50.0 + i * 0.1, timestamp=i * 60.0)
        result = analyze_trend(s, "cpu", threshold=80.0)
        assert result.confidence == "high"

    def test_already_breached(self):
        s = MetricSeries(max_samples=20)
        for i in range(5):
            s.add(85.0 + i, timestamp=i * 60.0)
        result = analyze_trend(s, "cpu", threshold=80.0, horizon_minutes=5.0)
        assert result.will_breach is True
        assert result.time_to_threshold_minutes == 0.0
