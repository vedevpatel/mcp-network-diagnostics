"""Tests for configuration tracking and correlation (P2b)."""
import asyncio
import json
import random
import time


from mcp_network.config import (
    ConfigSnapshot,
    ConfigChange,
    ConfigTracker,
    get_config_tracker,
)


def _fresh_collector():
    random.seed(42)
    import mcp_network.collectors.simulated as sim
    sim._collector = None
    collector = sim.SimulatedCollector()
    import mcp_network.collectors.config as cfg
    cfg._collector_instance = collector
    return collector


def _reset_config_tracker():
    import mcp_network.config.tracker as tracker_mod
    tracker_mod._config_tracker = None


def _run(coro):
    return json.loads(asyncio.run(coro))


# ===========================================================================
# Unit tests — ConfigTracker
# ===========================================================================


class TestConfigSnapshot:
    def test_age_calculation(self):
        snapshot = ConfigSnapshot(
            device_id="R1",
            config_hash="abc123",
            timestamp=time.time() - 100.0,
        )
        assert 99.0 < snapshot.age_seconds < 101.0


class TestConfigChange:
    def test_age_calculation(self):
        change = ConfigChange(
            device_id="R1",
            change_time=time.time() - 50.0,
            old_hash="abc",
            new_hash="def",
        )
        assert 49.0 < change.age_seconds < 51.0


class TestConfigTracker:
    def setup_method(self):
        self.tracker = ConfigTracker()

    def test_add_first_snapshot(self):
        change = self.tracker.add_snapshot("R1", "config line 1\nconfig line 2")
        assert change is None  # no previous snapshot
        assert "R1" in self.tracker.snapshots
        assert len(self.tracker.snapshots["R1"]) == 1

    def test_add_identical_snapshot_no_change(self):
        config = "config line 1\nconfig line 2"
        self.tracker.add_snapshot("R1", config)
        change = self.tracker.add_snapshot("R1", config)
        assert change is None

    def test_add_different_snapshot_detects_change(self):
        self.tracker.add_snapshot("R1", "config A")
        change = self.tracker.add_snapshot("R1", "config B")
        assert change is not None
        assert change.device_id == "R1"
        assert change.old_hash != change.new_hash

    def test_get_latest_snapshot(self):
        self.tracker.add_snapshot("R1", "config 1")
        self.tracker.add_snapshot("R1", "config 2")
        latest = self.tracker.get_latest_snapshot("R1")
        assert latest is not None
        assert latest.config_text == "config 2"

    def test_get_latest_snapshot_not_found(self):
        latest = self.tracker.get_latest_snapshot("R99")
        assert latest is None

    def test_get_snapshot_at_time(self):
        t1 = time.time()
        self.tracker.add_snapshot("R1", "config 1", timestamp=t1)
        time.sleep(0.01)
        t2 = time.time()
        self.tracker.add_snapshot("R1", "config 2", timestamp=t2)

        # Get snapshot at t1.5 should return first one
        snap = self.tracker.get_snapshot_at_time("R1", t1 + 0.005)
        assert snap is not None
        assert snap.config_text == "config 1"

    def test_get_snapshot_at_time_future(self):
        t1 = time.time()
        self.tracker.add_snapshot("R1", "config 1", timestamp=t1)

        # Get snapshot at future time returns latest
        snap = self.tracker.get_snapshot_at_time("R1", t1 + 100.0)
        assert snap is not None
        assert snap.config_text == "config 1"

    def test_get_changes_in_window(self):
        now = time.time()
        self.tracker.add_snapshot("R1", "config 1", timestamp=now - 100.0)
        self.tracker.add_snapshot("R1", "config 2", timestamp=now - 50.0)
        self.tracker.add_snapshot("R1", "config 3", timestamp=now - 10.0)

        # Window of 60 seconds should capture last 2 changes
        changes = self.tracker.get_changes_in_window("R1", window_seconds=60.0)
        assert len(changes) == 2

    def test_get_all_recent_changes(self):
        now = time.time()
        self.tracker.add_snapshot("R1", "config 1", timestamp=now - 100.0)
        self.tracker.add_snapshot("R1", "config 2", timestamp=now - 10.0)
        self.tracker.add_snapshot("R2", "config A", timestamp=now - 100.0)
        self.tracker.add_snapshot("R2", "config B", timestamp=now - 5.0)

        changes = self.tracker.get_all_recent_changes(window_seconds=60.0)
        assert len(changes) == 2
        # Should be sorted by time, most recent first
        assert changes[0].device_id == "R2"

    def test_diff_configs_no_change(self):
        t1 = time.time()
        self.tracker.add_snapshot("R1", "config A", timestamp=t1)
        self.tracker.add_snapshot("R1", "config A", timestamp=t1 + 10.0)

        diff = self.tracker.diff_configs("R1", t1, t1 + 10.0)
        assert diff == "No changes detected"

    def test_diff_configs_with_changes(self):
        t1 = time.time()
        self.tracker.add_snapshot("R1", "line1\nline2\nline3", timestamp=t1)
        self.tracker.add_snapshot("R1", "line1\nline2_modified\nline4", timestamp=t1 + 10.0)

        diff = self.tracker.diff_configs("R1", t1, t1 + 10.0)
        assert diff is not None
        assert "+" in diff or "-" in diff

    def test_diff_configs_snapshot_not_found(self):
        diff = self.tracker.diff_configs("R99", time.time(), time.time() + 10.0)
        assert diff is None

    def test_has_recent_change(self):
        now = time.time()
        self.tracker.add_snapshot("R1", "config 1", timestamp=now - 100.0)
        self.tracker.add_snapshot("R1", "config 2", timestamp=now - 10.0)

        assert self.tracker.has_recent_change("R1", window_seconds=60.0) is True
        assert self.tracker.has_recent_change("R1", window_seconds=5.0) is False

    def test_get_change_history(self):
        now = time.time()
        self.tracker.add_snapshot("R1", "config 1", timestamp=now - 100.0)
        self.tracker.add_snapshot("R1", "config 2", timestamp=now - 50.0)
        self.tracker.add_snapshot("R1", "config 3", timestamp=now - 10.0)

        history = self.tracker.get_change_history("R1", limit=10)
        assert len(history) == 2  # 2 changes detected


# ===========================================================================
# Integration tests — Tools
# ===========================================================================


class TestConfigTools:
    def setup_method(self):
        self.collector = _fresh_collector()
        _reset_config_tracker()

    def test_get_config_history_output_structure(self):
        from mcp_network.tools import get_config_history

        # Generate some snapshots
        for _ in range(3):
            self.collector.refresh()

        result = _run(get_config_history("R1"))
        assert "device_id" in result
        assert "changes" in result
        assert "latest_config_hash" in result
        assert "change_count" in result

    def test_get_config_history_empty(self):
        from mcp_network.tools import get_config_history

        result = _run(get_config_history("R99"))
        assert result["change_count"] == 0
        assert result["changes"] == []

    def test_compare_configs_output_structure(self):
        from mcp_network.tools import compare_configs

        # Generate snapshots
        self.collector.refresh()
        time.sleep(0.01)
        t1 = time.time()
        time.sleep(0.01)
        self.collector.refresh()
        time.sleep(0.01)
        t2 = time.time()

        result = _run(compare_configs("R1", str(t1), str(t2)))
        if "error" not in result:
            assert "device_id" in result
            assert "diff" in result
            assert "changed" in result

    def test_check_config_correlation_output_structure(self):
        from mcp_network.tools import check_config_correlation

        self.collector.refresh()
        result = _run(check_config_correlation("R1"))

        assert "device_id" in result
        assert "had_recent_change" in result
        assert "changes" in result
        assert "window_seconds" in result


# ===========================================================================
# Simulated collector integration
# ===========================================================================


class TestSimulatedCollectorConfigTracking:
    def setup_method(self):
        self.collector = _fresh_collector()
        _reset_config_tracker()

    def test_refresh_creates_snapshots(self):

        tracker = get_config_tracker()
        self.collector.refresh()

        # All 10 devices should have snapshots
        for i in range(1, 11):
            device_id = f"R{i}"
            snapshot = tracker.get_latest_snapshot(device_id)
            assert snapshot is not None
            assert snapshot.device_id == device_id

    def test_config_change_injection_at_call_10(self):

        tracker = get_config_tracker()

        # Refresh 9 times (calls 1-9)
        for _ in range(9):
            self.collector.refresh()

        # No change yet on R3
        changes_before = tracker.get_change_history("R3")
        count_before = len(changes_before)

        # Refresh again (call 10 — triggers config change on R3)
        self.collector.refresh()

        changes_after = tracker.get_change_history("R3")
        count_after = len(changes_after)

        # Should detect a config change
        assert count_after > count_before

    def test_get_config_method(self):
        config = self.collector.get_config("R1")
        assert "hostname R1" in config
        assert "interface" in config
