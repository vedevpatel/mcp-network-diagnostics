"""Trend analysis and anomaly detection for network metrics."""
from mcp_network.trends.store import MetricStore, MetricSeries, MetricSample
from mcp_network.trends.analyzer import (
    TrendResult,
    analyze_trend,
    compute_rate,
    compute_acceleration,
    estimate_time_to_threshold,
)
from mcp_network.trends.anomaly import (
    AnomalyResult,
    detect_zscore_anomaly,
    detect_rate_shift,
    detect_volatility_change,
    detect_all_anomalies,
)

__all__ = [
    "MetricStore",
    "MetricSeries",
    "MetricSample",
    "TrendResult",
    "analyze_trend",
    "compute_rate",
    "compute_acceleration",
    "estimate_time_to_threshold",
    "AnomalyResult",
    "detect_zscore_anomaly",
    "detect_rate_shift",
    "detect_volatility_change",
    "detect_all_anomalies",
]
