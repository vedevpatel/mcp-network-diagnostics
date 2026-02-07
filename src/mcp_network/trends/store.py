"""In-memory metric history storage using ring buffers."""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from mcp_network.models.network import Device


@dataclass
class MetricSample:
    """Single metric observation at a point in time."""
    timestamp: float
    value: float


@dataclass
class MetricSeries:
    """Ring buffer of the last N samples for one metric."""
    max_samples: int = 20
    _samples: deque = field(default_factory=deque)

    def __post_init__(self):
        self._samples = deque(self._samples, maxlen=self.max_samples)

    def add(self, value: float, timestamp: float | None = None) -> None:
        ts = timestamp if timestamp is not None else time.monotonic()
        self._samples.append(MetricSample(timestamp=ts, value=value))

    @property
    def samples(self) -> list[MetricSample]:
        return list(self._samples)

    @property
    def count(self) -> int:
        return len(self._samples)

    @property
    def latest(self) -> MetricSample | None:
        return self._samples[-1] if self._samples else None


class MetricStore:
    """Per-device, per-metric history store.

    Keys are (device_id, metric_name) tuples where metric_name follows:
        "cpu"                     - device CPU usage
        "memory"                  - device memory usage
        "interface:<name>:util"   - interface utilization
        "interface:<name>:errors" - interface error count
    """

    def __init__(self, max_samples: int = 20):
        self._max_samples = max_samples
        self._series: dict[tuple[str, str], MetricSeries] = {}

    def _get_or_create(self, device_id: str, metric: str) -> MetricSeries:
        key = (device_id, metric)
        if key not in self._series:
            self._series[key] = MetricSeries(max_samples=self._max_samples)
        return self._series[key]

    def record_device(self, device: Device, timestamp: float | None = None) -> None:
        """Record all metrics from a Device snapshot."""
        ts = timestamp if timestamp is not None else time.monotonic()
        did = device.device_id
        self._get_or_create(did, "cpu").add(device.cpu_usage, ts)
        self._get_or_create(did, "memory").add(device.memory_usage, ts)
        for iface in device.interfaces:
            self._get_or_create(did, f"interface:{iface.name}:util").add(
                iface.utilization, ts
            )
            self._get_or_create(did, f"interface:{iface.name}:errors").add(
                float(iface.errors), ts
            )

    def record_all(self, devices: dict[str, Device], timestamp: float | None = None) -> None:
        """Record metrics from all devices in a snapshot."""
        ts = timestamp if timestamp is not None else time.monotonic()
        for device in devices.values():
            self.record_device(device, ts)

    def get_series(self, device_id: str, metric: str) -> MetricSeries | None:
        return self._series.get((device_id, metric))

    def get_device_metrics(self, device_id: str) -> dict[str, MetricSeries]:
        """Return all series for a given device."""
        return {
            metric: series
            for (did, metric), series in self._series.items()
            if did == device_id
        }

    def clear(self) -> None:
        self._series.clear()
