"""Tests for causal root cause analysis (P2c)."""
import asyncio
import json
import random
import time

import networkx as nx

from mcp_network.causal import (
    AnomalyEvent,
    CausalEdge,
    CausalGraph,
    build_causal_graph,
    identify_root_causes,
)


def _fresh_collector():
    random.seed(42)
    import mcp_network.collectors.simulated as sim
    sim._collector = None
    collector = sim.SimulatedCollector()
    import mcp_network.collectors.config as cfg
    cfg._collector_instance = collector
    return collector


def _reset_store():
    import mcp_network.tools as tools_mod
    from mcp_network.trends.store import MetricStore
    tools_mod._metric_store = MetricStore()


def _run(coro):
    return json.loads(asyncio.run(coro))


# ===========================================================================
# Unit tests — Causal graph construction
# ===========================================================================


class TestAnomalyEvent:
    def test_event_id(self):
        event = AnomalyEvent(
            device_id="R1",
            metric="cpu",
            anomaly_type="zscore",
            timestamp=time.time(),
            severity="high",
            score=5.0,
        )
        assert event.event_id == "R1:cpu:zscore"


class TestCausalEdge:
    def test_time_delta(self):
        cause = AnomalyEvent("R1", "cpu", "zscore", 100.0, "high", 5.0)
        effect = AnomalyEvent("R2", "cpu", "zscore", 150.0, "medium", 3.0)
        edge = CausalEdge(cause, effect, confidence=0.8)
        assert edge.time_delta_seconds == 50.0


class TestCausalGraph:
    def test_initialization(self):
        event1 = AnomalyEvent("R1", "cpu", "zscore", 100.0, "high", 5.0)
        event2 = AnomalyEvent("R2", "cpu", "zscore", 150.0, "medium", 3.0)
        edge = CausalEdge(event1, event2, confidence=0.8)

        graph = CausalGraph(events=[event1, event2], edges=[edge])
        assert len(graph.graph.nodes) == 2
        assert len(graph.graph.edges) == 1

    def test_get_root_candidates(self):
        event1 = AnomalyEvent("R1", "cpu", "zscore", 100.0, "high", 5.0)
        event2 = AnomalyEvent("R2", "cpu", "zscore", 150.0, "medium", 3.0)
        edge = CausalEdge(event1, event2, confidence=0.8)

        graph = CausalGraph(events=[event1, event2], edges=[edge])
        roots = graph.get_root_candidates()
        assert len(roots) == 1
        assert roots[0].device_id == "R1"

    def test_get_leaf_events(self):
        event1 = AnomalyEvent("R1", "cpu", "zscore", 100.0, "high", 5.0)
        event2 = AnomalyEvent("R2", "cpu", "zscore", 150.0, "medium", 3.0)
        edge = CausalEdge(event1, event2, confidence=0.8)

        graph = CausalGraph(events=[event1, event2], edges=[edge])
        leaves = graph.get_leaf_events()
        assert len(leaves) == 1
        assert leaves[0].device_id == "R2"

    def test_get_downstream_events(self):
        event1 = AnomalyEvent("R1", "cpu", "zscore", 100.0, "high", 5.0)
        event2 = AnomalyEvent("R2", "cpu", "zscore", 150.0, "medium", 3.0)
        event3 = AnomalyEvent("R3", "cpu", "zscore", 200.0, "low", 2.0)
        edge1 = CausalEdge(event1, event2, confidence=0.8)
        edge2 = CausalEdge(event2, event3, confidence=0.7)

        graph = CausalGraph(events=[event1, event2, event3], edges=[edge1, edge2])
        downstream = graph.get_downstream_events(event1)
        assert len(downstream) == 2
        device_ids = {e.device_id for e in downstream}
        assert device_ids == {"R2", "R3"}

    def test_compute_impact_score(self):
        event1 = AnomalyEvent("R1", "cpu", "zscore", 100.0, "high", 5.0)
        event2 = AnomalyEvent("R2", "cpu", "zscore", 150.0, "medium", 3.0)
        edge = CausalEdge(event1, event2, confidence=0.8)

        graph = CausalGraph(events=[event1, event2], edges=[edge])
        impact = graph.compute_impact_score(event1)
        # high severity = 3.0, 1 downstream device = 1.0, total = 4.0
        assert impact == 4.0


class TestBuildCausalGraph:
    def test_empty_events(self):
        topology = nx.Graph()
        graph = build_causal_graph([], topology)
        assert len(graph.events) == 0
        assert len(graph.edges) == 0

    def test_single_event(self):
        topology = nx.Graph()
        topology.add_node("R1")
        event = AnomalyEvent("R1", "cpu", "zscore", 100.0, "high", 5.0)
        graph = build_causal_graph([event], topology)
        assert len(graph.events) == 1
        assert len(graph.edges) == 0

    def test_same_device_events_high_confidence(self):
        topology = nx.Graph()
        topology.add_node("R1")
        event1 = AnomalyEvent("R1", "cpu", "zscore", 100.0, "high", 5.0)
        event2 = AnomalyEvent("R1", "memory", "zscore", 150.0, "medium", 3.0)

        graph = build_causal_graph([event1, event2], topology)
        assert len(graph.edges) == 1
        assert graph.edges[0].confidence >= 0.7  # same device = high confidence

    def test_connected_devices_creates_edge(self):
        topology = nx.Graph()
        topology.add_node("R1")
        topology.add_node("R2")
        topology.add_edge("R1", "R2")

        event1 = AnomalyEvent("R1", "cpu", "zscore", 100.0, "high", 5.0)
        event2 = AnomalyEvent("R2", "cpu", "zscore", 150.0, "medium", 3.0)

        graph = build_causal_graph([event1, event2], topology)
        assert len(graph.edges) == 1
        assert graph.edges[0].cause_event.device_id == "R1"
        assert graph.edges[0].effect_event.device_id == "R2"

    def test_time_window_constraint(self):
        topology = nx.Graph()
        topology.add_node("R1")
        topology.add_node("R2")
        topology.add_edge("R1", "R2")

        event1 = AnomalyEvent("R1", "cpu", "zscore", 100.0, "high", 5.0)
        event2 = AnomalyEvent("R2", "cpu", "zscore", 500.0, "medium", 3.0)  # 400s later

        # Default window is 300s
        graph = build_causal_graph([event1, event2], topology, max_time_window_seconds=300.0)
        assert len(graph.edges) == 0  # too far apart

    def test_severity_escalation_boosts_confidence(self):
        topology = nx.Graph()
        topology.add_node("R1")
        event1 = AnomalyEvent("R1", "cpu", "zscore", 100.0, "low", 2.0)
        event2 = AnomalyEvent("R1", "memory", "zscore", 150.0, "high", 5.0)

        graph = build_causal_graph([event1, event2], topology)
        # Confidence should be boosted due to severity escalation
        assert graph.edges[0].confidence > 0.8


class TestIdentifyRootCauses:
    def test_empty_graph(self):
        graph = CausalGraph(events=[], edges=[])
        results = identify_root_causes(graph)
        assert len(results) == 0

    def test_single_root_cause(self):
        event1 = AnomalyEvent("R1", "cpu", "zscore", 100.0, "high", 5.0)
        event2 = AnomalyEvent("R2", "cpu", "zscore", 150.0, "medium", 3.0)
        edge = CausalEdge(event1, event2, confidence=0.8)

        graph = CausalGraph(events=[event1, event2], edges=[edge])
        results = identify_root_causes(graph)

        assert len(results) >= 1
        assert results[0].root_event.device_id == "R1"
        assert results[0].confidence > 0.0

    def test_root_cause_fields(self):
        event1 = AnomalyEvent("R1", "cpu", "zscore", 100.0, "high", 5.0)
        event2 = AnomalyEvent("R2", "cpu", "zscore", 150.0, "medium", 3.0)
        edge = CausalEdge(event1, event2, confidence=0.8)

        graph = CausalGraph(events=[event1, event2], edges=[edge])
        results = identify_root_causes(graph)

        rc = results[0]
        assert "R1" in rc.affected_devices
        assert "R2" in rc.affected_devices
        assert rc.impact_score > 0.0
        assert len(rc.evidence) > 0
        assert len(rc.explanation) > 0

    def test_min_confidence_filter(self):
        event1 = AnomalyEvent("R1", "cpu", "zscore", 100.0, "low", 2.0)
        event2 = AnomalyEvent("R2", "cpu", "zscore", 150.0, "low", 2.0)
        edge = CausalEdge(event1, event2, confidence=0.3)

        graph = CausalGraph(events=[event1, event2], edges=[edge])
        results = identify_root_causes(graph, min_confidence=0.9)
        # Should filter out low-confidence root causes
        assert len(results) == 0


# ===========================================================================
# Integration tests — Tool
# ===========================================================================


class TestExplainIncidentTool:
    def setup_method(self):
        self.collector = _fresh_collector()
        _reset_store()

    def test_output_structure(self):
        from mcp_network.tools import explain_incident

        # Generate enough data for anomalies
        for _ in range(12):
            _run(explain_incident())

        result = _run(explain_incident())
        assert "root_causes" in result
        assert "causal_graph" in result
        assert "affected_devices" in result
        assert "timeline" in result
        assert "explanation" in result

    def test_no_anomalies(self):
        from mcp_network.tools import explain_incident

        # Only 2 snapshots - not enough for anomaly detection
        _run(explain_incident())
        result = _run(explain_incident())

        assert result["explanation"] == "No anomalies detected in recent data."
        assert result["root_causes"] == []

    def test_with_anomalies(self):
        from mcp_network.tools import explain_incident

        # Run enough to trigger R2 CPU spike (calls 8-10)
        for _ in range(13):
            _run(explain_incident())

        result = _run(explain_incident())

        # Should have detected some anomalies
        if result["root_causes"]:
            rc = result["root_causes"][0]
            assert "device_id" in rc
            assert "metric" in rc
            assert "confidence" in rc
            assert "affected_devices" in rc

    def test_timeline_ordering(self):
        from mcp_network.tools import explain_incident

        for _ in range(10):
            _run(explain_incident())

        result = _run(explain_incident())

        # Timeline should be chronologically ordered if events exist
        if result["timeline"]:
            timestamps = [event["timestamp"] for event in result["timeline"]]
            assert timestamps == sorted(timestamps)

    def test_causal_graph_structure(self):
        from mcp_network.tools import explain_incident

        for _ in range(12):
            _run(explain_incident())

        result = _run(explain_incident())

        assert "events" in result["causal_graph"]
        assert "edges" in result["causal_graph"]

    def test_context_all(self):
        from mcp_network.tools import explain_incident

        for _ in range(5):
            _run(explain_incident("all"))

        result = _run(explain_incident("all"))
        assert "affected_devices" in result

    def test_context_specific_device(self):
        from mcp_network.tools import explain_incident

        for _ in range(5):
            _run(explain_incident("R1"))

        result = _run(explain_incident("R1"))
        # Should still return valid structure
        assert "root_causes" in result
        assert "timeline" in result
