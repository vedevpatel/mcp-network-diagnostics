"""Tests for collection health tracking (P2a)."""
import asyncio
import json
import random

import pytest

from mcp_network.collectors.health import (
    DeviceHealth,
    CollectionHealth,
    HealthTracker,
    get_health_tracker,
)


def _fresh_collector():
    random.seed(42)
    import mcp_network.collectors.simulated as sim
    sim._collector = None
    collector = sim.SimulatedCollector()
    import mcp_network.collectors.config as cfg
    cfg._collector_instance = collector
    return collector


def _reset_health():
    import mcp_network.collectors.health as health_mod
    health_mod._health_tracker = None


def _run(coro):
    return json.loads(asyncio.run(coro))


# ===========================================================================
# Unit tests — HealthTracker
# ===========================================================================


class TestDeviceHealth:
    def test_failure_rate_zero_when_no_attempts(self):
        health = DeviceHealth(device_id="R1", reachable=True)
        assert health.failure_rate == 0.0

    def test_failure_rate_calculation(self):
        health = DeviceHealth(
            device_id="R1",
            reachable=True,
            total_attempts=10,
            total_failures=3,
        )
        assert health.failure_rate == 0.3

    def test_is_stale_threshold(self):
        health = DeviceHealth(device_id="R1", reachable=True, data_age_seconds=301.0)
        assert health.is_stale is True

        health.data_age_seconds = 299.0
        assert health.is_stale is False

    def test_staleness_levels(self):
        health = DeviceHealth(device_id="R1", reachable=True, data_age_seconds=60.0)
        assert health.staleness_level == "fresh"

        health.data_age_seconds = 200.0
        assert health.staleness_level == "aging"

        health.data_age_seconds = 400.0
        assert health.staleness_level == "stale"

        health.data_age_seconds = 700.0
        assert health.staleness_level == "very_stale"


class TestHealthTracker:
    def setup_method(self):
        self.tracker = HealthTracker()

    def test_record_success_creates_device(self):
        self.tracker.record_success("R1")
        assert "R1" in self.tracker.devices
        assert self.tracker.devices["R1"].reachable is True

    def test_record_success_increments_counters(self):
        self.tracker.record_success("R1")
        health = self.tracker.devices["R1"]
        assert health.consecutive_successes == 1
        assert health.consecutive_failures == 0
        assert health.total_attempts == 1
        assert health.total_failures == 0

    def test_record_failure_creates_device(self):
        self.tracker.record_failure("R1", "Connection timeout")
        assert "R1" in self.tracker.devices
        assert self.tracker.devices["R1"].reachable is False

    def test_record_failure_increments_counters(self):
        self.tracker.record_failure("R1", "Connection timeout")
        health = self.tracker.devices["R1"]
        assert health.consecutive_failures == 1
        assert health.consecutive_successes == 0
        assert health.total_attempts == 1
        assert health.total_failures == 1
        assert health.last_error == "Connection timeout"

    def test_alternating_success_failure(self):
        self.tracker.record_success("R1")
        self.tracker.record_failure("R1", "Error")
        self.tracker.record_success("R1")

        health = self.tracker.devices["R1"]
        assert health.consecutive_successes == 1
        assert health.consecutive_failures == 0
        assert health.total_attempts == 3
        assert health.total_failures == 1
        assert health.failure_rate == pytest.approx(1.0 / 3.0)

    def test_get_health_summary_empty(self):
        summary = self.tracker.get_health_summary()
        assert summary.total_devices == 0
        assert summary.reachable_devices == 0
        assert summary.collection_quality_score == 0.0

    def test_get_health_summary_all_reachable(self):
        for i in range(1, 6):
            self.tracker.record_success(f"R{i}")

        summary = self.tracker.get_health_summary()
        assert summary.total_devices == 5
        assert summary.reachable_devices == 5
        assert summary.unreachable_devices == 0
        assert summary.collection_quality_score > 0.9

    def test_get_health_summary_mixed(self):
        self.tracker.record_success("R1")
        self.tracker.record_success("R2")
        self.tracker.record_failure("R3", "Error")
        self.tracker.record_failure("R4", "Error")

        summary = self.tracker.get_health_summary()
        assert summary.total_devices == 4
        assert summary.reachable_devices == 2
        assert summary.unreachable_devices == 2
        assert summary.reachability_percentage == 50.0

    def test_get_device_health(self):
        self.tracker.record_success("R1")
        health = self.tracker.get_device_health("R1")
        assert health is not None
        assert health.device_id == "R1"

    def test_get_device_health_not_found(self):
        health = self.tracker.get_device_health("R99")
        assert health is None


# ===========================================================================
# Integration tests — Tools
# ===========================================================================


class TestGetCollectionHealthTool:
    def setup_method(self):
        self.collector = _fresh_collector()
        _reset_health()

    def test_output_structure(self):
        from mcp_network.tools import get_collection_health

        # Run refresh to populate health tracker
        self.collector.refresh()

        result = _run(get_collection_health())
        assert "collection_quality_score" in result
        assert "reachability_percentage" in result
        assert "device_health" in result
        assert "stale_devices" in result
        assert "unreachable_devices" in result
        assert "summary" in result

    def test_all_devices_healthy(self):
        from mcp_network.tools import get_collection_health

        self.collector.refresh()
        result = _run(get_collection_health())

        # Simulated collector always succeeds
        assert result["reachable_devices"] == 10
        assert result["unreachable_devices_count"] == 0
        assert result["collection_quality_score"] >= 0.9

    def test_device_health_details(self):
        from mcp_network.tools import get_collection_health

        self.collector.refresh()
        result = _run(get_collection_health())

        for device_id, health in result["device_health"].items():
            assert "reachable" in health
            assert "staleness" in health
            assert "data_age_seconds" in health
            assert "failure_rate" in health
            assert health["reachable"] is True  # simulated always succeeds
            assert health["staleness"] == "fresh"  # just refreshed


# ===========================================================================
# Simulated collector integration
# ===========================================================================


class TestSimulatedCollectorHealthTracking:
    def setup_method(self):
        self.collector = _fresh_collector()
        _reset_health()

    def test_refresh_records_success(self):
        from mcp_network.collectors.health import get_health_tracker

        tracker = get_health_tracker()
        self.collector.refresh()

        # All 10 devices should be recorded as successful
        for i in range(1, 11):
            device_id = f"R{i}"
            health = tracker.get_device_health(device_id)
            assert health is not None
            assert health.reachable is True
            assert health.total_attempts == 1

    def test_multiple_refreshes_increment_attempts(self):
        from mcp_network.collectors.health import get_health_tracker

        tracker = get_health_tracker()

        for _ in range(3):
            self.collector.refresh()

        health = tracker.get_device_health("R1")
        assert health.total_attempts == 3
        assert health.consecutive_successes == 3
