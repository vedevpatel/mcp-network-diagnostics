"""Statistical anomaly detection over metric series."""
from __future__ import annotations

import math
from dataclasses import dataclass

from mcp_network.trends.store import MetricSeries
from mcp_network.trends.analyzer import compute_rate


# --- Configuration defaults ---
DEFAULT_Z_SCORE_THRESHOLD = 2.0
DEFAULT_RATE_SHIFT_THRESHOLD = 3.0
DEFAULT_VOLATILITY_RATIO_THRESHOLD = 3.0
DEFAULT_MIN_SAMPLES = 5


@dataclass
class AnomalyResult:
    """Single anomaly detection on one metric series."""
    metric_name: str
    anomaly_type: str        # "zscore", "rate_shift", "volatility"
    current_value: float
    baseline_mean: float
    baseline_stddev: float
    score: float
    severity: str            # "low", "medium", "high"
    confidence: str          # "low", "high"
    description: str


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _stddev(values: list[float], mean_val: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean_val) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _classify_severity(score: float) -> str:
    if score > 4.0:
        return "high"
    if score > 3.0:
        return "medium"
    return "low"


def _classify_confidence(sample_count: int) -> str:
    return "high" if sample_count >= 15 else "low"


def detect_zscore_anomaly(
    series: MetricSeries,
    metric_name: str,
    threshold: float = DEFAULT_Z_SCORE_THRESHOLD,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> AnomalyResult | None:
    """Detect if the latest value deviates significantly from the baseline.

    Baseline = mean/stddev of all samples except the latest.
    Falls back to absolute deviation if stddev ≈ 0.
    """
    samples = series.samples
    if len(samples) < min_samples:
        return None

    baseline_values = [s.value for s in samples[:-1]]
    latest = samples[-1].value

    mean_val = _mean(baseline_values)
    std_val = _stddev(baseline_values, mean_val)

    # Zero-stddev fallback (constant metric)
    if std_val < 0.001:
        deviation = abs(latest - mean_val)
        if deviation > 0.5:
            score = deviation / 0.5
            return AnomalyResult(
                metric_name=metric_name,
                anomaly_type="zscore",
                current_value=latest,
                baseline_mean=round(mean_val, 4),
                baseline_stddev=0.0,
                score=round(score, 2),
                severity=_classify_severity(score),
                confidence=_classify_confidence(len(samples)),
                description=f"{metric_name} deviated from constant baseline "
                            f"({round(latest, 1)} vs {round(mean_val, 1)})",
            )
        return None

    z = abs(latest - mean_val) / std_val
    if z <= threshold:
        return None

    return AnomalyResult(
        metric_name=metric_name,
        anomaly_type="zscore",
        current_value=latest,
        baseline_mean=round(mean_val, 4),
        baseline_stddev=round(std_val, 4),
        score=round(z, 2),
        severity=_classify_severity(z),
        confidence=_classify_confidence(len(samples)),
        description=f"{metric_name} is {round(z, 1)} standard deviations "
                    f"from baseline ({round(latest, 1)} vs mean {round(mean_val, 1)})",
    )


def detect_rate_shift(
    series: MetricSeries,
    metric_name: str,
    threshold: float = DEFAULT_RATE_SHIFT_THRESHOLD,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> AnomalyResult | None:
    """Detect if the rate of change suddenly shifted.

    Compares recent rate (last 1/3) to historical rate (first 2/3).
    """
    samples = series.samples
    effective_min = max(min_samples, 6)
    if len(samples) < effective_min:
        return None

    split = len(samples) * 2 // 3
    historical = samples[:split]
    recent = samples[split:]

    hist_rate = compute_rate(historical)
    recent_rate = compute_rate(recent)

    # Compute stddev of per-sample deltas in historical window
    hist_deltas = []
    for i in range(1, len(historical)):
        dt = (historical[i].timestamp - historical[i - 1].timestamp) / 60.0
        if dt > 0:
            hist_deltas.append(
                (historical[i].value - historical[i - 1].value) / dt
            )

    if not hist_deltas:
        return None

    delta_mean = _mean(hist_deltas)
    delta_std = _stddev(hist_deltas, delta_mean)

    # If historical rate variance is near zero, use absolute rate difference
    if delta_std < 0.001:
        rate_diff = abs(recent_rate - hist_rate)
        if rate_diff > 0.5:
            score = rate_diff / 0.5
        else:
            return None
    else:
        score = abs(recent_rate - hist_rate) / delta_std

    if score <= threshold:
        return None

    latest = samples[-1].value
    baseline_mean = _mean([s.value for s in historical])

    return AnomalyResult(
        metric_name=metric_name,
        anomaly_type="rate_shift",
        current_value=latest,
        baseline_mean=round(baseline_mean, 4),
        baseline_stddev=round(delta_std, 4),
        score=round(score, 2),
        severity=_classify_severity(score),
        confidence=_classify_confidence(len(samples)),
        description=f"{metric_name} rate shifted from {round(hist_rate, 2)}/min "
                    f"to {round(recent_rate, 2)}/min",
    )


def detect_volatility_change(
    series: MetricSeries,
    metric_name: str,
    threshold: float = DEFAULT_VOLATILITY_RATIO_THRESHOLD,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> AnomalyResult | None:
    """Detect if a metric became significantly more volatile.

    Compares stddev of second half to first half.
    """
    samples = series.samples
    effective_min = max(min_samples, 8)
    if len(samples) < effective_min:
        return None

    mid = len(samples) // 2
    first_values = [s.value for s in samples[:mid]]
    second_values = [s.value for s in samples[mid:]]

    first_mean = _mean(first_values)
    second_mean = _mean(second_values)
    first_std = _stddev(first_values, first_mean)
    second_std = _stddev(second_values, second_mean)

    # Zero-stddev fallback
    if first_std < 0.001:
        if second_std > 1.0:
            score = second_std / 1.0
        else:
            return None
    else:
        score = second_std / first_std

    if score <= threshold:
        return None

    latest = samples[-1].value

    return AnomalyResult(
        metric_name=metric_name,
        anomaly_type="volatility",
        current_value=latest,
        baseline_mean=round(first_mean, 4),
        baseline_stddev=round(first_std, 4),
        score=round(score, 2),
        severity=_classify_severity(score),
        confidence=_classify_confidence(len(samples)),
        description=f"{metric_name} volatility increased {round(score, 1)}x "
                    f"(stddev {round(first_std, 2)} → {round(second_std, 2)})",
    )


def detect_all_anomalies(
    series: MetricSeries,
    metric_name: str,
    z_score_threshold: float = DEFAULT_Z_SCORE_THRESHOLD,
    rate_shift_threshold: float = DEFAULT_RATE_SHIFT_THRESHOLD,
    volatility_ratio_threshold: float = DEFAULT_VOLATILITY_RATIO_THRESHOLD,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> list[AnomalyResult]:
    """Run all anomaly detectors and return any hits."""
    results = []
    for detector, thresh in [
        (detect_zscore_anomaly, z_score_threshold),
        (detect_rate_shift, rate_shift_threshold),
        (detect_volatility_change, volatility_ratio_threshold),
    ]:
        result = detector(series, metric_name, threshold=thresh, min_samples=min_samples)
        if result is not None:
            results.append(result)
    return results
