"""Statistical trend analysis: derivatives, acceleration, time-to-threshold."""
from __future__ import annotations

from dataclasses import dataclass

from mcp_network.trends.store import MetricSeries, MetricSample


@dataclass
class TrendResult:
    """Result of analyzing a single metric's trend."""
    metric_name: str
    current_value: float
    rate_per_minute: float
    acceleration_per_minute: float
    direction: str  # "rising", "falling", "stable"
    time_to_threshold_minutes: float | None
    will_breach: bool
    sample_count: int
    confidence: str  # "low", "medium", "high"


def compute_rate(samples: list[MetricSample]) -> float:
    """Average rate of change (units/min) via OLS linear regression."""
    n = len(samples)
    if n < 2:
        return 0.0

    t0 = samples[0].timestamp
    times = [(s.timestamp - t0) / 60.0 for s in samples]
    values = [s.value for s in samples]

    if times[-1] - times[0] == 0:
        return 0.0

    t_mean = sum(times) / n
    v_mean = sum(values) / n

    numerator = sum((t - t_mean) * (v - v_mean) for t, v in zip(times, values))
    denominator = sum((t - t_mean) ** 2 for t in times)

    if denominator == 0:
        return 0.0

    return numerator / denominator


def compute_acceleration(samples: list[MetricSample]) -> float:
    """Second derivative (units/min^2) via split-window rate comparison."""
    if len(samples) < 4:
        return 0.0

    mid = len(samples) // 2
    first_half = samples[:mid]
    second_half = samples[mid:]

    rate_first = compute_rate(first_half)
    rate_second = compute_rate(second_half)

    t_mid_first = (first_half[0].timestamp + first_half[-1].timestamp) / 2
    t_mid_second = (second_half[0].timestamp + second_half[-1].timestamp) / 2
    dt_minutes = (t_mid_second - t_mid_first) / 60.0

    if dt_minutes == 0:
        return 0.0

    return (rate_second - rate_first) / dt_minutes


def estimate_time_to_threshold(
    current_value: float,
    rate_per_minute: float,
    threshold: float,
) -> float | None:
    """Minutes until value reaches threshold at constant rate.

    Returns None if not trending toward threshold.
    Returns 0.0 if already breached.
    """
    if current_value >= threshold:
        return 0.0
    if rate_per_minute <= 0:
        return None
    return (threshold - current_value) / rate_per_minute


def analyze_trend(
    series: MetricSeries,
    metric_name: str,
    threshold: float,
    horizon_minutes: float = 5.0,
) -> TrendResult | None:
    """Full trend analysis for a single metric series.

    Returns None if fewer than 2 samples.
    """
    samples = series.samples
    if len(samples) < 2:
        return None

    current = samples[-1].value
    rate = compute_rate(samples)
    accel = compute_acceleration(samples)

    # Direction classification (dead zone at ±0.1 units/min)
    if abs(rate) < 0.1:
        direction = "stable"
    elif rate > 0:
        direction = "rising"
    else:
        direction = "falling"

    tte = estimate_time_to_threshold(current, rate, threshold)
    will_breach = tte is not None and tte <= horizon_minutes

    # Confidence based on sample count
    if len(samples) >= 15:
        confidence = "high"
    elif len(samples) >= 5:
        confidence = "medium"
    else:
        confidence = "low"

    return TrendResult(
        metric_name=metric_name,
        current_value=current,
        rate_per_minute=round(rate, 4),
        acceleration_per_minute=round(accel, 4),
        direction=direction,
        time_to_threshold_minutes=round(tte, 2) if tte is not None else None,
        will_breach=will_breach,
        sample_count=len(samples),
        confidence=confidence,
    )
