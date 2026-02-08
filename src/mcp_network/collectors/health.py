"""Collector health tracking and data quality monitoring."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DeviceHealth:
    """Health status for a single device."""
    device_id: str
    reachable: bool
    last_success_time: Optional[float] = None
    last_failure_time: Optional[float] = None
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_attempts: int = 0
    total_failures: int = 0
    last_error: Optional[str] = None
    data_age_seconds: float = 0.0

    @property
    def failure_rate(self) -> float:
        """Compute failure rate (0.0 to 1.0)."""
        if self.total_attempts == 0:
            return 0.0
        return self.total_failures / self.total_attempts

    @property
    def is_stale(self) -> bool:
        """Check if data is stale (>5 minutes old)."""
        return self.data_age_seconds > 300.0

    @property
    def staleness_level(self) -> str:
        """Classify staleness: fresh, aging, stale, very_stale."""
        if self.data_age_seconds < 120.0:
            return "fresh"
        elif self.data_age_seconds < 300.0:
            return "aging"
        elif self.data_age_seconds < 600.0:
            return "stale"
        else:
            return "very_stale"


@dataclass
class CollectionHealth:
    """Overall collection health summary."""
    total_devices: int
    reachable_devices: int
    unreachable_devices: int
    stale_devices: int
    collection_quality_score: float  # 0.0 to 1.0
    timestamp: float = field(default_factory=time.time)
    device_health: dict[str, DeviceHealth] = field(default_factory=dict)

    @property
    def reachability_percentage(self) -> float:
        """Percentage of devices currently reachable."""
        if self.total_devices == 0:
            return 0.0
        return (self.reachable_devices / self.total_devices) * 100.0

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Collection Quality: {self.collection_quality_score:.1%}",
            f"Reachability: {self.reachable_devices}/{self.total_devices} devices ({self.reachability_percentage:.1f}%)",
        ]
        if self.stale_devices > 0:
            lines.append(f"Stale Data: {self.stale_devices} devices")
        if self.unreachable_devices > 0:
            lines.append(f"Unreachable: {self.unreachable_devices} devices")
        return " | ".join(lines)


class HealthTracker:
    """Track health metrics for all devices in the topology."""

    def __init__(self):
        """Initialize health tracker."""
        self.devices: dict[str, DeviceHealth] = {}
        self.last_collection_time: float = 0.0

    def record_success(self, device_id: str) -> None:
        """Record successful collection for a device."""
        if device_id not in self.devices:
            self.devices[device_id] = DeviceHealth(device_id=device_id, reachable=True)

        health = self.devices[device_id]
        health.reachable = True
        health.last_success_time = time.time()
        health.consecutive_successes += 1
        health.consecutive_failures = 0
        health.total_attempts += 1
        health.last_error = None
        health.data_age_seconds = 0.0

    def record_failure(self, device_id: str, error: str) -> None:
        """Record failed collection for a device."""
        if device_id not in self.devices:
            self.devices[device_id] = DeviceHealth(device_id=device_id, reachable=False)

        health = self.devices[device_id]
        health.reachable = False
        health.last_failure_time = time.time()
        health.consecutive_failures += 1
        health.consecutive_successes = 0
        health.total_attempts += 1
        health.total_failures += 1
        health.last_error = error

    def update_staleness(self) -> None:
        """Update data age for all devices based on last success time."""
        now = time.time()
        for health in self.devices.values():
            if health.last_success_time is not None:
                health.data_age_seconds = now - health.last_success_time

    def get_health_summary(self) -> CollectionHealth:
        """Compute overall collection health."""
        self.update_staleness()

        total = len(self.devices)
        reachable = sum(1 for h in self.devices.values() if h.reachable)
        unreachable = total - reachable
        stale = sum(1 for h in self.devices.values() if h.is_stale)

        # Quality score factors:
        # - Reachability (50% weight)
        # - Freshness (30% weight)
        # - Low failure rate (20% weight)
        if total == 0:
            quality_score = 0.0
        else:
            reachability_score = reachable / total
            fresh_count = sum(1 for h in self.devices.values() if not h.is_stale and h.reachable)
            freshness_score = fresh_count / total
            avg_failure_rate = sum(h.failure_rate for h in self.devices.values()) / total
            reliability_score = 1.0 - avg_failure_rate

            quality_score = (
                0.5 * reachability_score +
                0.3 * freshness_score +
                0.2 * reliability_score
            )

        return CollectionHealth(
            total_devices=total,
            reachable_devices=reachable,
            unreachable_devices=unreachable,
            stale_devices=stale,
            collection_quality_score=quality_score,
            device_health={k: v for k, v in self.devices.items()},
        )

    def get_device_health(self, device_id: str) -> Optional[DeviceHealth]:
        """Get health status for a specific device."""
        return self.devices.get(device_id)


# Global singleton
_health_tracker: Optional[HealthTracker] = None


def get_health_tracker() -> HealthTracker:
    """Get the global health tracker instance."""
    global _health_tracker
    if _health_tracker is None:
        _health_tracker = HealthTracker()
    return _health_tracker
