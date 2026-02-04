"""
Unit tests for SimulatedCollector, pathfinder, and the diagnostic tools.

Every test that touches the simulated topology pins random.seed(42) and
resets the collector singleton so the metric values and graph shape are
fully deterministic.  The exact numbers in the assertions below were
derived from that seed — see the comment block at the top of each section.
"""

import asyncio
import json
import random

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _run(coro):
    """Run an async tool function synchronously."""
    return json.loads(asyncio.run(coro))


# ===========================================================================
# SimulatedCollector — shape & congestion pattern
# ===========================================================================
# seed-42 congestion rules:
#   cpu_congested  = i % 3 == 0  → R3, R6, R9
#   iface_congested = i % 4 == 0 → R4, R8
# ===========================================================================


class TestSimulatedCollector:
    def setup_method(self):
        self.collector = _fresh_collector()

    def test_ten_devices(self):
        assert len(self.collector.devices) == 10

    def test_device_ids(self):
        assert set(self.collector.devices.keys()) == {f"R{i}" for i in range(1, 11)}

    def test_sixteen_links(self):
        # 14 mesh edges + 2 explicit alternate-path shortcuts
        assert len(self.collector.links) == 16

    def test_graph_node_count(self):
        assert len(self.collector.graph.nodes) == 10

    def test_graph_edge_count(self):
        assert len(self.collector.graph.edges) == 16

    def test_local_device(self):
        assert self.collector.local_device == "R1"

    # -- CPU congestion pattern --

    def test_cpu_congested_devices(self):
        congested = {did for did, d in self.collector.devices.items() if d.cpu_usage > 80}
        assert congested == {"R3", "R6", "R9"}

    def test_cpu_healthy_devices_below_threshold(self):
        for did, d in self.collector.devices.items():
            if did not in {"R3", "R6", "R9"}:
                assert d.cpu_usage <= 80, f"{did} cpu={d.cpu_usage}"

    # -- Interface congestion pattern --

    def test_interface_congested_devices(self):
        """R4 and R8 have all four interfaces above 80 % util and >100 errors."""
        for did in ("R4", "R8"):
            for iface in self.collector.devices[did].interfaces:
                assert iface.utilization > 80, f"{did}/{iface.name} util={iface.utilization}"
                assert iface.errors > 100, f"{did}/{iface.name} errors={iface.errors}"

    def test_interface_healthy_devices(self):
        """All other devices have all interfaces below 80 % util and <=100 errors."""
        for did, d in self.collector.devices.items():
            if did in ("R4", "R8"):
                continue
            for iface in d.interfaces:
                assert iface.utilization <= 80, f"{did}/{iface.name} util={iface.utilization}"
                assert iface.errors <= 100, f"{did}/{iface.name} errors={iface.errors}"

    def test_each_device_has_four_interfaces(self):
        for did, d in self.collector.devices.items():
            assert len(d.interfaces) == 4, f"{did} has {len(d.interfaces)} interfaces"

    def test_all_interfaces_are_up(self):
        for d in self.collector.devices.values():
            for iface in d.interfaces:
                assert iface.status == "up"


# ===========================================================================
# Pathfinder
# ===========================================================================
# seed-42 Dijkstra (latency-weighted) shortest paths:
#   R1 → R10 :  R1-R3-R5-R7-R9-R10   11.20 ms
#   R1 → R7  :  R1-R3-R5-R7            5.40 ms
#   R1 → R5  :  R1-R3-R5               3.70 ms
# ===========================================================================


class TestPathfinder:
    def setup_method(self):
        self.collector = _fresh_collector()
        self.graph = self.collector.graph

    # -- find_path --

    def test_shortest_path_r1_r10(self):
        from mcp_network.graph.pathfinder import find_path

        assert find_path(self.graph, "R1", "R10") == ["R1", "R3", "R5", "R7", "R9", "R10"]

    def test_shortest_path_r1_r7(self):
        from mcp_network.graph.pathfinder import find_path

        assert find_path(self.graph, "R1", "R7") == ["R1", "R3", "R5", "R7"]

    def test_find_path_unknown_device_raises(self):
        from mcp_network.graph.pathfinder import find_path

        with pytest.raises(ValueError, match="not found"):
            find_path(self.graph, "R1", "R99")

    # -- calculate_total_latency --

    def test_total_latency_r1_r10(self):
        from mcp_network.graph.pathfinder import calculate_total_latency

        path = ["R1", "R3", "R5", "R7", "R9", "R10"]
        assert round(calculate_total_latency(self.graph, path), 2) == 11.20

    def test_total_latency_single_hop(self):
        from mcp_network.graph.pathfinder import calculate_total_latency

        # R1-R3 edge is 1.8 ms
        assert calculate_total_latency(self.graph, ["R1", "R3"]) == 1.8

    # -- find_alternate_paths --

    def test_alternate_paths_excludes_primary(self):
        from mcp_network.graph.pathfinder import find_alternate_paths

        primary = ["R1", "R3", "R5", "R7", "R9", "R10"]
        results = find_alternate_paths(self.graph, primary, {"R3", "R9"})
        paths = [r["path"] for r in results]
        assert primary not in paths

    def test_alternate_paths_sorted_avoids_all_first(self):
        from mcp_network.graph.pathfinder import find_alternate_paths

        primary = ["R1", "R3", "R5", "R7", "R9", "R10"]
        results = find_alternate_paths(self.graph, primary, {"R3", "R9"})

        # The best alternate avoids both R3 and R9
        best = results[0]
        assert best["avoids_all"] is True
        assert "R3" not in best["path"]
        assert "R9" not in best["path"]

    def test_alternate_paths_best_is_r1_r4_r6_r8_r10(self):
        from mcp_network.graph.pathfinder import find_alternate_paths

        primary = ["R1", "R3", "R5", "R7", "R9", "R10"]
        results = find_alternate_paths(self.graph, primary, {"R3", "R9"})
        assert results[0]["path"] == ["R1", "R4", "R6", "R8", "R10"]
        assert results[0]["total_latency_ms"] == 11.30

    def test_alternate_paths_empty_primary_returns_nothing(self):
        from mcp_network.graph.pathfinder import find_alternate_paths

        assert find_alternate_paths(self.graph, [], {"R3"}) == []
        assert find_alternate_paths(self.graph, ["R1"], {"R3"}) == []

    def test_alternate_paths_partial_avoids(self):
        """R2→R9: bottlenecks {R4,R6,R8,R9}, best alternate still hits R9."""
        from mcp_network.graph.pathfinder import find_alternate_paths

        primary = ["R2", "R4", "R6", "R8", "R9"]
        results = find_alternate_paths(self.graph, primary, {"R4", "R6", "R8", "R9"})
        best = results[0]
        assert best["avoids_all"] is False
        # It should still avoid some subset
        assert len(best["avoids"]) > 0


# ===========================================================================
# diagnose_latency — end-to-end tool behaviour
# ===========================================================================


class TestDiagnoseLatency:
    def setup_method(self):
        self._fresh = _fresh_collector()

    # -- healthy path (no findings) --

    def test_healthy_path_no_findings(self):
        """R1→R2: both healthy, single hop, no congestion on the link interfaces."""
        from mcp_network.tools import diagnose_latency

        result = _run(diagnose_latency("R1", "R2"))
        assert result["health_status"] == "healthy"
        assert result["findings"] == []
        assert result["alternate_path"] is None
        assert "No anomalies" in result["summary"]

    # -- congested path with alternate --
    # R1→R10 primary hits R3 (cpu) and R9 (cpu).
    # Best alternate R1-R4-R6-R8-R10 avoids both.

    def test_congested_path_has_findings(self):
        from mcp_network.tools import diagnose_latency

        result = _run(diagnose_latency("R1", "R10"))
        assert result["health_status"] == "issue_detected"
        assert len(result["findings"]) > 0

    def test_congested_path_findings_are_on_expected_devices(self):
        from mcp_network.tools import diagnose_latency

        result = _run(diagnose_latency("R1", "R10"))
        finding_devices = {f["device"] for f in result["findings"]}
        # R3 and R9 are the cpu-congested devices on this path
        assert finding_devices == {"R3", "R9"}

    def test_congested_path_alternate_avoids_all(self):
        from mcp_network.tools import diagnose_latency

        result = _run(diagnose_latency("R1", "R10"))
        alt = result["alternate_path"]
        assert alt is not None
        assert alt["avoids_all_bottlenecks"] is True
        assert alt["path"] == ["R1", "R4", "R6", "R8", "R10"]
        assert alt["total_latency_ms"] == 11.30

    def test_congested_path_recommendation_mentions_alternate(self):
        from mcp_network.tools import diagnose_latency

        result = _run(diagnose_latency("R1", "R10"))
        assert "Alternate path" in result["recommendation"]
        assert "avoids all bottlenecks" in result["recommendation"]

    def test_congested_path_summary_picks_worst_finding(self):
        """Both findings are high_cpu; summary should reference the higher value (R9 at 90.1)."""
        from mcp_network.tools import diagnose_latency

        result = _run(diagnose_latency("R1", "R10"))
        assert "R9" in result["summary"]
        assert "high cpu" in result["summary"]

    # -- partial-avoids alternate --
    # R2→R9 primary: bottlenecks on R4, R6, R8, R9.
    # Best alternate avoids R4/R6/R8 but still traverses R9.

    def test_partial_avoids_alternate(self):
        from mcp_network.tools import diagnose_latency

        result = _run(diagnose_latency("R2", "R9"))
        alt = result["alternate_path"]
        assert alt is not None
        assert alt["avoids_all_bottlenecks"] is False
        assert set(alt["avoids_devices"]) == {"R4", "R6", "R8"}

    def test_partial_avoids_recommendation_does_not_say_all(self):
        from mcp_network.tools import diagnose_latency

        result = _run(diagnose_latency("R2", "R9"))
        assert "avoids all bottlenecks" not in result["recommendation"]

    # -- unknown device --

    def test_unknown_device_returns_error(self):
        from mcp_network.tools import diagnose_latency

        result = _run(diagnose_latency("R1", "R99"))
        assert "error" in result


# ===========================================================================
# Threshold override behaviour
# ===========================================================================
# Verify that setting thresholds on the collector actually changes what
# gets flagged — the mechanism that the topology YAML block exercises.
# ===========================================================================


class TestThresholdOverride:
    def setup_method(self):
        self.collector = _fresh_collector()

    def test_lowered_cpu_threshold_flags_more_devices(self):
        """Default 80 % flags R3/R6/R9.  Drop to 50 % and R1/R10 join too."""
        self.collector.thresholds = {"cpu": 50.0, "utilization": 80.0, "errors": 100}

        from mcp_network.tools import diagnose_latency

        # R1→R10 path: R1(63.5), R3(88.6), R5(44.6), R7(20.3), R9(90.1), R10(63.9)
        # At 50 % threshold, R1, R3, R9, R10 should all appear
        result = _run(diagnose_latency("R1", "R10"))
        cpu_devices = {f["device"] for f in result["findings"] if f["type"] == "high_cpu"}
        assert cpu_devices == {"R1", "R3", "R9", "R10"}

    def test_raised_cpu_threshold_flags_nothing(self):
        """Set CPU threshold to 99 — nobody on R1→R10 breaches it."""
        self.collector.thresholds = {"cpu": 99.0, "utilization": 80.0, "errors": 100}

        from mcp_network.tools import diagnose_latency

        result = _run(diagnose_latency("R1", "R10"))
        cpu_findings = [f for f in result["findings"] if f["type"] == "high_cpu"]
        assert cpu_findings == []

    def test_interface_threshold_override(self):
        """R2→R9 primary goes through R4 (iface congested).  Raise util threshold
        to 95 and only the very highest interfaces survive."""
        self.collector.thresholds = {"cpu": 80.0, "utilization": 95.0, "errors": 100}

        from mcp_network.tools import diagnose_latency

        result = _run(diagnose_latency("R2", "R9"))
        util_findings = [f for f in result["findings"] if f["type"] == "high_utilization"]
        # At seed-42, R4 Gi0/0 is 93.7 — below 95.  Only R4 Gi0/3 (90.9) is also
        # below.  No R4 interface breaches 95, so no high_utilization findings on R4.
        r4_util = [f for f in util_findings if f["device"] == "R4"]
        assert r4_util == []
