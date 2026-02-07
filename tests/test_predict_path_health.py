"""Integration tests for predict_path_health tool and trend annotations."""
import asyncio
import json
import random

import pytest


def _fresh_collector():
    """Reset and return a seed-42 SimulatedCollector, wired into the global
    config singleton so that get_network() and the tools see it."""
    random.seed(42)
    import mcp_network.collectors.simulated as sim
    sim._collector = None
    collector = sim.SimulatedCollector()
    import mcp_network.collectors.config as cfg
    cfg._collector_instance = collector
    return collector


def _reset_store():
    """Reset the global metric store between tests."""
    import mcp_network.tools as tools_mod
    from mcp_network.trends.store import MetricStore
    tools_mod._metric_store = MetricStore()


def _run(coro):
    return json.loads(asyncio.run(coro))


# ===========================================================================
# predict_path_health
# ===========================================================================

class TestPredictPathHealth:
    def setup_method(self):
        self.collector = _fresh_collector()
        _reset_store()

    def test_returns_expected_keys(self):
        from mcp_network.tools import predict_path_health
        result = _run(predict_path_health("R1", "R10"))
        assert "path" in result
        assert "current_diagnosis" in result
        assert "predictions" in result
        assert "overall_risk" in result
        assert "horizon_minutes" in result
        assert "recommendation" in result
        assert "timestamp" in result

    def test_path_is_valid(self):
        from mcp_network.tools import predict_path_health
        result = _run(predict_path_health("R1", "R10"))
        assert result["path"][0] == "R1"
        assert result["path"][-1] == "R10"

    def test_current_diagnosis_has_findings(self):
        from mcp_network.tools import predict_path_health
        result = _run(predict_path_health("R1", "R10"))
        diag = result["current_diagnosis"]
        assert "findings" in diag
        assert "summary" in diag
        assert "health_status" in diag

    def test_overall_risk_valid_values(self):
        from mcp_network.tools import predict_path_health
        result = _run(predict_path_health("R1", "R10"))
        assert result["overall_risk"] in ("low", "medium", "high")

    def test_horizon_parameter_propagated(self):
        from mcp_network.tools import predict_path_health
        result = _run(predict_path_health("R1", "R10", horizon_minutes=10))
        assert result["horizon_minutes"] == 10

    def test_unknown_device_returns_error(self):
        from mcp_network.tools import predict_path_health
        result = _run(predict_path_health("R1", "R99"))
        assert "error" in result

    def test_same_device_path(self):
        from mcp_network.tools import predict_path_health
        result = _run(predict_path_health("R1", "R1"))
        assert result["path"] == ["R1"]

    def test_predictions_structure(self):
        from mcp_network.tools import predict_path_health
        result = _run(predict_path_health("R1", "R10"))
        for pred in result["predictions"]:
            assert "device" in pred
            assert "metric" in pred
            assert "direction" in pred
            assert "confidence" in pred
            assert "will_breach" in pred


class TestPredictPathHealthMultiSnapshot:
    """Test that multiple calls build history and detect trends."""

    def setup_method(self):
        self.collector = _fresh_collector()
        _reset_store()

    def test_multiple_calls_build_history(self):
        from mcp_network.tools import predict_path_health
        # Call multiple times — each call records a snapshot via _snapshot_metrics
        for _ in range(5):
            _run(predict_path_health("R1", "R2"))

        import mcp_network.tools as tools_mod
        series = tools_mod._metric_store.get_series("R1", "cpu")
        assert series is not None
        assert series.count == 5

    def test_congested_devices_trend_upward_after_many_snapshots(self):
        """R3 CPU should trend upward since it's a congested device."""
        from mcp_network.tools import predict_path_health
        # Build enough history for a meaningful trend
        for _ in range(10):
            _run(predict_path_health("R1", "R3"))

        import mcp_network.tools as tools_mod
        from mcp_network.trends.analyzer import analyze_trend
        series = tools_mod._metric_store.get_series("R3", "cpu")
        assert series is not None
        trend = analyze_trend(series, "cpu", threshold=100.0)
        assert trend is not None
        assert trend.rate_per_minute > 0  # trending up


# ===========================================================================
# Trend annotations on existing tools
# ===========================================================================

class TestGetDeviceStatusTrends:
    def setup_method(self):
        self.collector = _fresh_collector()
        _reset_store()

    def test_trends_key_present(self):
        from mcp_network.tools import get_device_status
        result = _run(get_device_status("R1"))
        assert "trends" in result

    def test_trends_populated_after_multiple_calls(self):
        from mcp_network.tools import get_device_status
        # First call records first snapshot — trends need >=2 samples
        _run(get_device_status("R1"))
        result = _run(get_device_status("R1"))
        trends = result["trends"]
        assert len(trends) > 0
        for t in trends:
            assert "metric" in t
            assert "direction" in t


class TestDiagnoseLatencyTrendWarnings:
    def setup_method(self):
        self.collector = _fresh_collector()
        _reset_store()

    def test_trend_warnings_key_present(self):
        from mcp_network.tools import diagnose_latency
        result = _run(diagnose_latency("R1", "R10"))
        assert "trend_warnings" in result

    def test_trend_warnings_is_list(self):
        from mcp_network.tools import diagnose_latency
        result = _run(diagnose_latency("R1", "R10"))
        assert isinstance(result["trend_warnings"], list)


# ===========================================================================
# SimulatedCollector refresh
# ===========================================================================

class TestSimulatedRefresh:
    def setup_method(self):
        self.collector = _fresh_collector()

    def test_refresh_changes_metrics(self):
        cpu_before = self.collector.devices["R1"].cpu_usage
        self.collector.refresh()
        cpu_after = self.collector.devices["R1"].cpu_usage
        assert cpu_before != cpu_after

    def test_refresh_is_deterministic(self):
        """Two collectors refreshed the same number of times produce same values."""
        c1 = _fresh_collector()
        c2 = _fresh_collector()
        for _ in range(5):
            c1.refresh()
            c2.refresh()
        assert c1.devices["R3"].cpu_usage == c2.devices["R3"].cpu_usage

    def test_congested_cpu_trends_upward(self):
        """R3 (i%3==0) should have rising CPU after many refreshes."""
        initial_cpu = self.collector.devices["R3"].cpu_usage
        for _ in range(20):
            self.collector.refresh()
        final_cpu = self.collector.devices["R3"].cpu_usage
        assert final_cpu > initial_cpu

    def test_congested_iface_trends_upward(self):
        """R4 (i%4==0) interfaces should have rising utilization."""
        initial_util = self.collector.devices["R4"].interfaces[0].utilization
        for _ in range(20):
            self.collector.refresh()
        final_util = self.collector.devices["R4"].interfaces[0].utilization
        assert final_util > initial_util

    def test_call_count_increments(self):
        assert self.collector._call_count == 0
        self.collector.refresh()
        assert self.collector._call_count == 1
        self.collector.refresh()
        assert self.collector._call_count == 2
