"""Baseline storage and comparison for edge network diagnostics.

Stores historical "good" network performance to enable:
- "Your connection is 4x slower than normal"
- "DNS is taking 180ms, normally 45ms"
- Anomaly detection on edge metrics
"""

import json
import os
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from statistics import mean, stdev


@dataclass
class BaselineSnapshot:
    """Single baseline measurement."""
    timestamp: float
    gateway_latency_ms: float
    gateway_loss_pct: float
    dns_resolution_ms: float
    external_latency_ms: float  # Ping to 8.8.8.8
    external_loss_pct: float
    wifi_signal_dbm: Optional[int] = None
    wifi_quality: Optional[str] = None


@dataclass
class BaselineComparison:
    """Comparison of current metrics vs baseline."""
    metric: str
    current_value: float
    baseline_mean: float
    baseline_stddev: float
    deviation_factor: float  # How many times worse/better
    is_anomalous: bool
    severity: str  # "normal", "warning", "critical"
    explanation: str


class BaselineStorage:
    """Manages baseline storage and comparison for edge metrics."""

    def __init__(self, storage_path: Optional[str] = None):
        """Initialize baseline storage.

        Args:
            storage_path: Path to JSON file for storage.
                         Defaults to ~/.mcp_network/edge_baseline.json
        """
        if storage_path is None:
            home = Path.home()
            storage_dir = home / ".mcp_network"
            storage_dir.mkdir(exist_ok=True)
            storage_path = str(storage_dir / "edge_baseline.json")

        self.storage_path = storage_path
        self.snapshots: list[BaselineSnapshot] = []
        self.max_snapshots = 100  # Keep last 100 measurements

        self._load()

    def add_snapshot(self, snapshot: BaselineSnapshot) -> None:
        """Add a baseline snapshot.

        Args:
            snapshot: New baseline measurement
        """
        self.snapshots.append(snapshot)

        # Trim to max size (FIFO)
        if len(self.snapshots) > self.max_snapshots:
            self.snapshots = self.snapshots[-self.max_snapshots:]

        self._save()

    def get_baseline_stats(self, metric: str) -> tuple[float, float, int]:
        """Get baseline statistics for a metric.

        Args:
            metric: Metric name (e.g., "gateway_latency_ms")

        Returns:
            Tuple of (mean, stddev, sample_count)
        """
        if not self.snapshots:
            return (0.0, 0.0, 0)

        values = []
        for snapshot in self.snapshots:
            value = getattr(snapshot, metric, None)
            if value is not None and isinstance(value, (int, float)):
                values.append(float(value))

        if not values:
            return (0.0, 0.0, 0)

        mean_val = mean(values)
        stddev_val = stdev(values) if len(values) > 1 else 0.0

        return (mean_val, stddev_val, len(values))

    def compare_to_baseline(
        self,
        current: BaselineSnapshot,
        z_score_threshold: float = 2.0,
    ) -> list[BaselineComparison]:
        """Compare current metrics to baseline.

        Args:
            current: Current measurement
            z_score_threshold: Z-score threshold for anomaly detection

        Returns:
            List of comparisons for each metric
        """
        comparisons = []

        # Metrics to compare (excluding timestamp and categorical fields)
        metrics = [
            "gateway_latency_ms",
            "gateway_loss_pct",
            "dns_resolution_ms",
            "external_latency_ms",
            "external_loss_pct",
        ]

        # Add WiFi signal if available
        if current.wifi_signal_dbm is not None:
            metrics.append("wifi_signal_dbm")

        for metric in metrics:
            current_value = getattr(current, metric)
            if current_value is None:
                continue

            baseline_mean, baseline_stddev, sample_count = self.get_baseline_stats(metric)

            # Need at least 5 samples for reliable baseline
            if sample_count < 5:
                continue

            # Calculate deviation
            if baseline_mean == 0:
                # Avoid division by zero
                deviation_factor = 1.0
                z_score = 0.0
            else:
                deviation_factor = current_value / baseline_mean

                # Z-score for anomaly detection
                if baseline_stddev > 0:
                    z_score = abs(current_value - baseline_mean) / baseline_stddev
                else:
                    # Constant baseline - use absolute deviation
                    z_score = abs(current_value - baseline_mean)

            # Determine if anomalous
            is_anomalous = z_score > z_score_threshold

            # Severity classification
            if not is_anomalous:
                severity = "normal"
            elif z_score > 4.0 or deviation_factor > 3.0:
                severity = "critical"
            else:
                severity = "warning"

            # Human-readable explanation
            explanation = self._generate_explanation(
                metric, current_value, baseline_mean, deviation_factor, severity
            )

            comparisons.append(BaselineComparison(
                metric=metric,
                current_value=current_value,
                baseline_mean=baseline_mean,
                baseline_stddev=baseline_stddev,
                deviation_factor=deviation_factor,
                is_anomalous=is_anomalous,
                severity=severity,
                explanation=explanation,
            ))

        return comparisons

    def _generate_explanation(
        self,
        metric: str,
        current: float,
        baseline: float,
        factor: float,
        severity: str,
    ) -> str:
        """Generate human-readable explanation of comparison."""
        # Metric display names
        display_names = {
            "gateway_latency_ms": "Gateway latency",
            "gateway_loss_pct": "Gateway packet loss",
            "dns_resolution_ms": "DNS resolution time",
            "external_latency_ms": "External latency",
            "external_loss_pct": "External packet loss",
            "wifi_signal_dbm": "WiFi signal strength",
        }

        name = display_names.get(metric, metric)

        # Units
        if "latency" in metric or "resolution" in metric:
            unit = "ms"
        elif "loss" in metric:
            unit = "%"
        elif "signal" in metric:
            unit = "dBm"
        else:
            unit = ""

        if severity == "normal":
            return f"{name} is normal ({current:.1f}{unit}, baseline {baseline:.1f}{unit})"

        # Worse vs better
        if metric == "wifi_signal_dbm":
            # WiFi signal: higher (less negative) is better
            if current > baseline:
                direction = "better"
            else:
                direction = "worse"
        else:
            # Latency/loss: lower is better
            if current > baseline:
                direction = "worse"
            else:
                direction = "better"

        # Format factor
        if direction == "worse":
            if factor >= 2.0:
                factor_str = f"{factor:.1f}x worse"
            else:
                pct_change = ((current - baseline) / baseline) * 100
                factor_str = f"{pct_change:.0f}% worse"
        else:
            pct_change = ((baseline - current) / baseline) * 100
            factor_str = f"{pct_change:.0f}% better"

        return f"{name}: {current:.1f}{unit} (normally {baseline:.1f}{unit}, {factor_str})"

    def clear_baseline(self) -> None:
        """Clear all baseline data."""
        self.snapshots = []
        self._save()

    def _save(self) -> None:
        """Save baseline to disk."""
        data = {
            "snapshots": [asdict(s) for s in self.snapshots],
            "max_snapshots": self.max_snapshots,
        }

        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self) -> None:
        """Load baseline from disk."""
        if not os.path.exists(self.storage_path):
            return

        try:
            with open(self.storage_path, "r") as f:
                data = json.load(f)

            self.max_snapshots = data.get("max_snapshots", 100)

            snapshots_data = data.get("snapshots", [])
            self.snapshots = [
                BaselineSnapshot(**s) for s in snapshots_data
            ]
        except (json.JSONDecodeError, TypeError, KeyError):
            # Corrupted file - start fresh
            self.snapshots = []
