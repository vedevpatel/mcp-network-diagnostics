"""Tests for baseline tracking and comparison."""
import asyncio
import json
import os
import tempfile



from mcp_network.baseline import BaselineStorage, BaselineSnapshot


def _run(coro):
    """Run async coroutine and return result."""
    return asyncio.run(coro)


class TestBaselineSnapshot:
    """Tests for BaselineSnapshot dataclass."""

    def test_snapshot_creation(self):
        """Test creating a baseline snapshot."""
        snapshot = BaselineSnapshot(
            timestamp=1234567890.0,
            gateway_latency_ms=5.2,
            gateway_loss_pct=0.0,
            dns_resolution_ms=12.5,
            external_latency_ms=18.3,
            external_loss_pct=0.0,
            wifi_signal_dbm=-52,
            wifi_quality="excellent",
        )

        assert snapshot.timestamp == 1234567890.0
        assert snapshot.gateway_latency_ms == 5.2
        assert snapshot.wifi_signal_dbm == -52
        assert snapshot.wifi_quality == "excellent"

    def test_snapshot_optional_wifi(self):
        """Test snapshot without WiFi data."""
        snapshot = BaselineSnapshot(
            timestamp=1234567890.0,
            gateway_latency_ms=5.2,
            gateway_loss_pct=0.0,
            dns_resolution_ms=12.5,
            external_latency_ms=18.3,
            external_loss_pct=0.0,
        )

        assert snapshot.wifi_signal_dbm is None
        assert snapshot.wifi_quality is None


class TestBaselineStorage:
    """Tests for BaselineStorage."""

    def setup_method(self):
        """Create temporary storage file."""
        self.temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json')
        self.temp_file.close()
        self.storage = BaselineStorage(storage_path=self.temp_file.name)

    def teardown_method(self):
        """Clean up temporary file."""
        if os.path.exists(self.temp_file.name):
            os.remove(self.temp_file.name)

    def test_storage_initialization(self):
        """Test storage initializes empty."""
        assert len(self.storage.snapshots) == 0
        assert self.storage.max_snapshots == 100

    def test_add_snapshot(self):
        """Test adding snapshots."""
        snapshot = BaselineSnapshot(
            timestamp=1234567890.0,
            gateway_latency_ms=5.0,
            gateway_loss_pct=0.0,
            dns_resolution_ms=10.0,
            external_latency_ms=15.0,
            external_loss_pct=0.0,
        )

        self.storage.add_snapshot(snapshot)
        assert len(self.storage.snapshots) == 1
        assert self.storage.snapshots[0] == snapshot

    def test_storage_persistence(self):
        """Test snapshots are saved and loaded."""
        snapshot = BaselineSnapshot(
            timestamp=1234567890.0,
            gateway_latency_ms=5.0,
            gateway_loss_pct=0.0,
            dns_resolution_ms=10.0,
            external_latency_ms=15.0,
            external_loss_pct=0.0,
        )

        self.storage.add_snapshot(snapshot)

        # Create new storage instance with same file
        storage2 = BaselineStorage(storage_path=self.temp_file.name)
        assert len(storage2.snapshots) == 1
        assert storage2.snapshots[0].timestamp == snapshot.timestamp
        assert storage2.snapshots[0].gateway_latency_ms == snapshot.gateway_latency_ms

    def test_max_snapshots_trimming(self):
        """Test that old snapshots are trimmed."""
        # Set low max for testing
        self.storage.max_snapshots = 10

        # Add 15 snapshots
        for i in range(15):
            snapshot = BaselineSnapshot(
                timestamp=1234567890.0 + i,
                gateway_latency_ms=5.0 + i,
                gateway_loss_pct=0.0,
                dns_resolution_ms=10.0,
                external_latency_ms=15.0,
                external_loss_pct=0.0,
            )
            self.storage.add_snapshot(snapshot)

        # Should only keep last 10
        assert len(self.storage.snapshots) == 10
        assert self.storage.snapshots[0].timestamp == 1234567895.0  # 5th snapshot (0-indexed)
        assert self.storage.snapshots[-1].timestamp == 1234567904.0  # 14th snapshot

    def test_get_baseline_stats_empty(self):
        """Test baseline stats with no data."""
        mean, stddev, count = self.storage.get_baseline_stats("gateway_latency_ms")
        assert mean == 0.0
        assert stddev == 0.0
        assert count == 0

    def test_get_baseline_stats_single_sample(self):
        """Test baseline stats with one sample."""
        snapshot = BaselineSnapshot(
            timestamp=1234567890.0,
            gateway_latency_ms=5.0,
            gateway_loss_pct=0.0,
            dns_resolution_ms=10.0,
            external_latency_ms=15.0,
            external_loss_pct=0.0,
        )
        self.storage.add_snapshot(snapshot)

        mean, stddev, count = self.storage.get_baseline_stats("gateway_latency_ms")
        assert mean == 5.0
        assert stddev == 0.0  # Only one sample
        assert count == 1

    def test_get_baseline_stats_multiple_samples(self):
        """Test baseline stats with multiple samples."""
        # Add samples: 5, 6, 7, 8, 9 (mean=7, stddev≈1.58)
        for i in range(5):
            snapshot = BaselineSnapshot(
                timestamp=1234567890.0 + i,
                gateway_latency_ms=5.0 + i,
                gateway_loss_pct=0.0,
                dns_resolution_ms=10.0,
                external_latency_ms=15.0,
                external_loss_pct=0.0,
            )
            self.storage.add_snapshot(snapshot)

        mean, stddev, count = self.storage.get_baseline_stats("gateway_latency_ms")
        assert mean == 7.0
        assert 1.5 < stddev < 1.6  # Approximately sqrt(2)
        assert count == 5

    def test_compare_to_baseline_insufficient_data(self):
        """Test comparison with insufficient baseline data."""
        # Add only 3 samples (need 5)
        for i in range(3):
            snapshot = BaselineSnapshot(
                timestamp=1234567890.0 + i,
                gateway_latency_ms=5.0,
                gateway_loss_pct=0.0,
                dns_resolution_ms=10.0,
                external_latency_ms=15.0,
                external_loss_pct=0.0,
            )
            self.storage.add_snapshot(snapshot)

        current = BaselineSnapshot(
            timestamp=1234567900.0,
            gateway_latency_ms=50.0,  # Much worse
            gateway_loss_pct=0.0,
            dns_resolution_ms=10.0,
            external_latency_ms=15.0,
            external_loss_pct=0.0,
        )

        comparisons = self.storage.compare_to_baseline(current)
        # Should return empty list due to insufficient samples
        assert len(comparisons) == 0

    def test_compare_to_baseline_normal(self):
        """Test comparison when current metrics are normal."""
        # Build baseline around 5.0ms
        for i in range(10):
            snapshot = BaselineSnapshot(
                timestamp=1234567890.0 + i,
                gateway_latency_ms=5.0 + (i % 3) * 0.5,  # 5.0, 5.5, 6.0, 5.0...
                gateway_loss_pct=0.0,
                dns_resolution_ms=10.0,
                external_latency_ms=15.0,
                external_loss_pct=0.0,
            )
            self.storage.add_snapshot(snapshot)

        # Current is within normal range
        current = BaselineSnapshot(
            timestamp=1234567900.0,
            gateway_latency_ms=5.5,
            gateway_loss_pct=0.0,
            dns_resolution_ms=10.0,
            external_latency_ms=15.0,
            external_loss_pct=0.0,
        )

        comparisons = self.storage.compare_to_baseline(current)

        # Find gateway_latency comparison
        gateway_comp = next(c for c in comparisons if c.metric == "gateway_latency_ms")
        assert not gateway_comp.is_anomalous
        assert gateway_comp.severity == "normal"

    def test_compare_to_baseline_anomalous(self):
        """Test comparison when current metrics are anomalous."""
        # Build baseline around 5.0ms
        for i in range(10):
            snapshot = BaselineSnapshot(
                timestamp=1234567890.0 + i,
                gateway_latency_ms=5.0,
                gateway_loss_pct=0.0,
                dns_resolution_ms=10.0,
                external_latency_ms=15.0,
                external_loss_pct=0.0,
            )
            self.storage.add_snapshot(snapshot)

        # Current is much worse
        current = BaselineSnapshot(
            timestamp=1234567900.0,
            gateway_latency_ms=50.0,  # 10x worse
            gateway_loss_pct=0.0,
            dns_resolution_ms=10.0,
            external_latency_ms=15.0,
            external_loss_pct=0.0,
        )

        comparisons = self.storage.compare_to_baseline(current)

        # Find gateway_latency comparison
        gateway_comp = next(c for c in comparisons if c.metric == "gateway_latency_ms")
        assert gateway_comp.is_anomalous
        assert gateway_comp.severity in ("warning", "critical")
        assert gateway_comp.deviation_factor == 10.0

    def test_compare_to_baseline_critical_severity(self):
        """Test critical severity classification."""
        # Build baseline
        for i in range(10):
            snapshot = BaselineSnapshot(
                timestamp=1234567890.0 + i,
                gateway_latency_ms=5.0,
                gateway_loss_pct=0.0,
                dns_resolution_ms=10.0,
                external_latency_ms=15.0,
                external_loss_pct=0.0,
            )
            self.storage.add_snapshot(snapshot)

        # Current is critically worse (>3x deviation)
        current = BaselineSnapshot(
            timestamp=1234567900.0,
            gateway_latency_ms=20.0,  # 4x worse
            gateway_loss_pct=0.0,
            dns_resolution_ms=10.0,
            external_latency_ms=15.0,
            external_loss_pct=0.0,
        )

        comparisons = self.storage.compare_to_baseline(current)
        gateway_comp = next(c for c in comparisons if c.metric == "gateway_latency_ms")
        assert gateway_comp.severity == "critical"

    def test_clear_baseline(self):
        """Test clearing baseline data."""
        # Add some snapshots
        for i in range(5):
            snapshot = BaselineSnapshot(
                timestamp=1234567890.0 + i,
                gateway_latency_ms=5.0,
                gateway_loss_pct=0.0,
                dns_resolution_ms=10.0,
                external_latency_ms=15.0,
                external_loss_pct=0.0,
            )
            self.storage.add_snapshot(snapshot)

        assert len(self.storage.snapshots) == 5

        self.storage.clear_baseline()
        assert len(self.storage.snapshots) == 0

    def test_explanation_generation(self):
        """Test human-readable explanation generation."""
        # Build baseline
        for i in range(10):
            snapshot = BaselineSnapshot(
                timestamp=1234567890.0 + i,
                gateway_latency_ms=5.0,
                gateway_loss_pct=0.0,
                dns_resolution_ms=10.0,
                external_latency_ms=15.0,
                external_loss_pct=0.0,
            )
            self.storage.add_snapshot(snapshot)

        # Current is worse
        current = BaselineSnapshot(
            timestamp=1234567900.0,
            gateway_latency_ms=15.0,  # 3x worse
            gateway_loss_pct=0.0,
            dns_resolution_ms=10.0,
            external_latency_ms=15.0,
            external_loss_pct=0.0,
        )

        comparisons = self.storage.compare_to_baseline(current)
        gateway_comp = next(c for c in comparisons if c.metric == "gateway_latency_ms")

        # Check explanation contains key info
        assert "Gateway latency" in gateway_comp.explanation
        assert "15.0ms" in gateway_comp.explanation
        assert "5.0ms" in gateway_comp.explanation


class TestBaselineTools:
    """Integration tests for baseline MCP tools."""

    def test_record_baseline(self):
        """Test record_baseline tool."""

        from mcp_network.tools import record_baseline
        result_json = _run(record_baseline())
        result = json.loads(result_json)

        assert result["status"] == "baseline_recorded"
        assert "metrics" in result
        assert "gateway_latency_ms" in result["metrics"]
        assert "dns_resolution_ms" in result["metrics"]
        assert result["total_baseline_samples"] >= 1

    def test_compare_to_baseline_insufficient_samples(self):
        """Test compare_to_baseline with insufficient data."""
        from mcp_network.tools import compare_to_baseline, _get_baseline_storage

        # Clear any existing baseline
        storage = _get_baseline_storage()
        storage.clear_baseline()

        result_json = _run(compare_to_baseline())
        result = json.loads(result_json)

        assert "error" in result
        assert "Insufficient baseline data" in result["error"]

    def test_record_and_compare_workflow(self):
        """Test full workflow: record baseline then compare."""

        from mcp_network.tools import record_baseline, compare_to_baseline, _get_baseline_storage

        # Clear baseline
        storage = _get_baseline_storage()
        storage.clear_baseline()

        # Record baseline 5 times
        for _ in range(5):
            _run(record_baseline())

        # Now compare should work
        result_json = _run(compare_to_baseline())
        result = json.loads(result_json)

        assert "error" not in result
        assert "overall_status" in result
        assert "comparisons" in result
        assert result["baseline_samples"] == 5

    def test_clear_baseline_tool(self):
        """Test clear_baseline tool."""

        from mcp_network.tools import record_baseline, clear_baseline, _get_baseline_storage

        # Record some data
        _run(record_baseline())
        _run(record_baseline())

        storage = _get_baseline_storage()
        assert len(storage.snapshots) >= 2

        # Clear
        result_json = _run(clear_baseline())
        result = json.loads(result_json)

        assert result["status"] == "baseline_cleared"
        assert len(storage.snapshots) == 0
