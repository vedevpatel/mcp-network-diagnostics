"""
Unit tests for PrometheusCollector and MetricCache.

PrometheusConnect is mocked at the class level — no real Prometheus
required.  Tests verify: cache TTL semantics, query-with-fallback,
device/link assembly from topology config.
"""

from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

import yaml

from mcp_network.collectors.prometheus import MetricCache, PrometheusCollector


# ===========================================================================
# MetricCache
# ===========================================================================


class TestMetricCache:
    def test_set_then_get_returns_value(self):
        cache = MetricCache(ttl_seconds=60)
        cache.set("k", 42.0)
        assert cache.get("k") == 42.0

    def test_missing_key_returns_none(self):
        cache = MetricCache(ttl_seconds=60)
        assert cache.get("nope") is None

    def test_expired_entry_returns_none(self):
        cache = MetricCache(ttl_seconds=1)
        cache.set("k", 99.0)
        # Backdate the timestamp so it looks expired
        cache._cache["k"] = (99.0, datetime.now() - timedelta(seconds=2))
        assert cache.get("k") is None

    def test_clear_empties_cache(self):
        cache = MetricCache(ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_overwrite_updates_timestamp(self):
        cache = MetricCache(ttl_seconds=60)
        cache.set("k", 1.0)
        cache._cache["k"] = (1.0, datetime.now() - timedelta(seconds=50))
        # Overwrite resets timestamp
        cache.set("k", 2.0)
        assert cache.get("k") == 2.0


# ===========================================================================
# PrometheusCollector — with mocked client and topology
# ===========================================================================

TOPO = {
    "local_device": "server1",
    "thresholds": {"cpu": 75, "utilization": 70, "errors": 50},
    "devices": [
        {
            "id": "server1",
            "type": "router",
            "prometheus_labels": {"instance": "10.0.0.1:9100", "job": "node_exporter"},
            "interfaces": [
                {"name": "eth0", "prometheus_name": "eth0", "link_speed_mbps": 1000},
            ],
        },
    ],
    "links": [
        {
            "src_device": "server1",
            "src_interface": "eth0",
            "dst_device": "server2",
            "dst_interface": "eth0",
            "default_latency_ms": 3.5,
        },
    ],
}


def _write_topo(tmp_path):
    p = tmp_path / "prom_topo.yaml"
    p.write_text(yaml.dump(TOPO))
    return str(p)


@patch("mcp_network.collectors.prometheus.PrometheusConnect")
class TestPrometheusCollectorInit:
    """Verify the collector wires up correctly when Prometheus responds."""

    def _make(self, mock_prom_cls, tmp_path, query_returns=None):
        """Helper: builds a collector with a mocked client.

        query_returns – list of dicts that custom_query returns in sequence.
        If None, every query returns a single result with value 42.0.
        """
        mock_client = MagicMock()
        if query_returns is None:
            mock_client.custom_query.return_value = [{"value": [0, "42.0"]}]
        else:
            mock_client.custom_query.side_effect = query_returns
        mock_prom_cls.return_value = mock_client

        topo_file = _write_topo(tmp_path)
        return PrometheusCollector(
            prometheus_url="http://localhost:9090",
            topology_file=topo_file,
            cache_ttl=30,
        )

    def test_local_device_loaded(self, mock_prom_cls, tmp_path):
        collector = self._make(mock_prom_cls, tmp_path)
        assert collector.local_device == "server1"

    def test_thresholds_loaded(self, mock_prom_cls, tmp_path):
        collector = self._make(mock_prom_cls, tmp_path)
        assert collector.thresholds == {"cpu": 75, "utilization": 70, "errors": 50}

    def test_device_populated(self, mock_prom_cls, tmp_path):
        collector = self._make(mock_prom_cls, tmp_path)
        assert "server1" in collector.devices
        device = collector.devices["server1"]
        assert device.device_id == "server1"
        assert device.device_type == "router"

    def test_device_metrics_come_from_queries(self, mock_prom_cls, tmp_path):
        # All queries return 42.0; cpu and memory should be 42.0
        collector = self._make(mock_prom_cls, tmp_path)
        device = collector.devices["server1"]
        assert device.cpu_usage == 42.0
        assert device.memory_usage == 42.0

    def test_interface_populated(self, mock_prom_cls, tmp_path):
        collector = self._make(mock_prom_cls, tmp_path)
        device = collector.devices["server1"]
        assert len(device.interfaces) == 1
        assert device.interfaces[0].name == "eth0"

    def test_link_populated(self, mock_prom_cls, tmp_path):
        collector = self._make(mock_prom_cls, tmp_path)
        assert len(collector.links) == 1
        assert collector.links[0].latency_ms == 3.5

    def test_graph_has_node_and_edge(self, mock_prom_cls, tmp_path):
        collector = self._make(mock_prom_cls, tmp_path)
        assert "server1" in collector.graph.nodes
        assert collector.graph.has_edge("server1", "server2")
        assert collector.graph.edges["server1", "server2"]["latency"] == 3.5


@patch("mcp_network.collectors.prometheus.PrometheusConnect")
class TestPrometheusQueryFallback:
    """_query_metric should fall back to default on exception."""

    def test_query_exception_returns_default(self, mock_prom_cls, tmp_path):
        mock_client = MagicMock()
        mock_client.custom_query.side_effect = Exception("connection refused")
        mock_prom_cls.return_value = mock_client

        topo_file = _write_topo(tmp_path)
        collector = PrometheusCollector(
            prometheus_url="http://localhost:9090",
            topology_file=topo_file,
            cache_ttl=30,
        )
        # CPU default is 50.0, memory default is 60.0 — verify both used
        device = collector.devices["server1"]
        assert device.cpu_usage == 50.0
        assert device.memory_usage == 60.0

    def test_empty_result_returns_default(self, mock_prom_cls, tmp_path):
        mock_client = MagicMock()
        mock_client.custom_query.return_value = []  # empty result set
        mock_prom_cls.return_value = mock_client

        topo_file = _write_topo(tmp_path)
        collector = PrometheusCollector(
            prometheus_url="http://localhost:9090",
            topology_file=topo_file,
            cache_ttl=30,
        )
        device = collector.devices["server1"]
        assert device.cpu_usage == 50.0


@patch("mcp_network.collectors.prometheus.PrometheusConnect")
class TestPrometheusInterfaceStatus:
    """Interface status: value 1.0 → up, anything else → down."""

    def _make_with_status(self, mock_prom_cls, tmp_path, status_value):
        mock_client = MagicMock()
        # Return 42.0 for everything except the status query (last query per interface)
        call_count = [0]

        def _side_effect(query):
            call_count[0] += 1
            if "node_network_up" in query:
                return [{"value": [0, str(status_value)]}]
            return [{"value": [0, "42.0"]}]

        mock_client.custom_query.side_effect = _side_effect
        mock_prom_cls.return_value = mock_client

        topo_file = _write_topo(tmp_path)
        return PrometheusCollector(
            prometheus_url="http://localhost:9090",
            topology_file=topo_file,
            cache_ttl=30,
        )

    def test_status_up_when_value_is_one(self, mock_prom_cls, tmp_path):
        collector = self._make_with_status(mock_prom_cls, tmp_path, 1.0)
        assert collector.devices["server1"].interfaces[0].status == "up"

    def test_status_down_when_value_is_zero(self, mock_prom_cls, tmp_path):
        collector = self._make_with_status(mock_prom_cls, tmp_path, 0.0)
        assert collector.devices["server1"].interfaces[0].status == "down"


@patch("mcp_network.collectors.prometheus.PrometheusConnect")
class TestPrometheusLinkLatencyDefault:
    """Link with no default_latency_ms should default to 2.0."""

    def test_missing_latency_defaults_to_2(self, mock_prom_cls, tmp_path):
        mock_client = MagicMock()
        mock_client.custom_query.return_value = [{"value": [0, "10.0"]}]
        mock_prom_cls.return_value = mock_client

        topo_no_latency = {
            "devices": [
                {
                    "id": "A",
                    "type": "router",
                    "prometheus_labels": {"instance": "10.0.0.1:9100"},
                    "interfaces": [],
                },
            ],
            "links": [
                {
                    "src_device": "A",
                    "src_interface": "eth0",
                    "dst_device": "B",
                    "dst_interface": "eth0",
                    # no default_latency_ms
                },
            ],
        }
        p = tmp_path / "topo.yaml"
        p.write_text(yaml.dump(topo_no_latency))

        collector = PrometheusCollector(
            prometheus_url="http://localhost:9090",
            topology_file=str(p),
            cache_ttl=30,
        )
        assert collector.links[0].latency_ms == 2.0
