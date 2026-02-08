"""Causal analysis for identifying root causes of network incidents."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import networkx as nx


@dataclass
class AnomalyEvent:
    """Single anomaly event with timing information."""
    device_id: str
    metric: str
    anomaly_type: str
    timestamp: float
    severity: str
    score: float

    @property
    def event_id(self) -> str:
        """Unique identifier for this event."""
        return f"{self.device_id}:{self.metric}:{self.anomaly_type}"


@dataclass
class CausalEdge:
    """Directed causal relationship between two anomaly events."""
    cause_event: AnomalyEvent
    effect_event: AnomalyEvent
    confidence: float  # 0.0 to 1.0
    evidence: list[str] = field(default_factory=list)

    @property
    def time_delta_seconds(self) -> float:
        """Time between cause and effect."""
        return self.effect_event.timestamp - self.cause_event.timestamp


@dataclass
class CausalGraph:
    """Graph representing causal relationships between anomaly events."""
    events: list[AnomalyEvent]
    edges: list[CausalEdge]
    graph: nx.DiGraph = field(default_factory=nx.DiGraph)

    def __post_init__(self):
        """Build NetworkX graph from events and edges."""
        for event in self.events:
            self.graph.add_node(event.event_id, event=event)
        for edge in self.edges:
            self.graph.add_edge(
                edge.cause_event.event_id,
                edge.effect_event.event_id,
                confidence=edge.confidence,
                edge=edge,
            )

    def get_root_candidates(self) -> list[AnomalyEvent]:
        """Get events with no incoming edges (potential root causes)."""
        roots = []
        for event in self.events:
            if self.graph.in_degree(event.event_id) == 0:
                roots.append(event)
        return roots

    def get_leaf_events(self) -> list[AnomalyEvent]:
        """Get events with no outgoing edges (downstream effects)."""
        leaves = []
        for event in self.events:
            if self.graph.out_degree(event.event_id) == 0:
                leaves.append(event)
        return leaves

    def get_downstream_events(self, event: AnomalyEvent) -> list[AnomalyEvent]:
        """Get all events downstream from this one."""
        try:
            descendants = nx.descendants(self.graph, event.event_id)
            return [self.graph.nodes[eid]["event"] for eid in descendants]
        except nx.NetworkXError:
            return []

    def compute_impact_score(self, event: AnomalyEvent) -> float:
        """Compute impact score based on downstream effects."""
        downstream = self.get_downstream_events(event)
        # Impact = number of affected devices + severity
        severity_map = {"low": 1.0, "medium": 2.0, "high": 3.0}
        base_score = severity_map.get(event.severity, 1.0)
        downstream_score = len(set(e.device_id for e in downstream))
        return base_score + downstream_score


@dataclass
class RootCauseResult:
    """Identified root cause with confidence and evidence."""
    root_event: AnomalyEvent
    confidence: float  # 0.0 to 1.0
    impact_score: float
    affected_devices: list[str]
    affected_events: list[AnomalyEvent]
    evidence: list[str]
    explanation: str


def build_causal_graph(
    events: list[AnomalyEvent],
    topology_graph: nx.Graph,
    max_time_window_seconds: float = 300.0,
) -> CausalGraph:
    """Build causal graph from anomaly events and network topology.

    Args:
        events: List of anomaly events
        topology_graph: Network topology (NetworkX graph)
        max_time_window_seconds: Max time between cause and effect

    Returns:
        CausalGraph with inferred causal edges
    """
    # Sort events by timestamp
    sorted_events = sorted(events, key=lambda e: e.timestamp)

    edges = []

    # For each pair of events, check if causal relationship is plausible
    for i, cause in enumerate(sorted_events):
        for effect in sorted_events[i + 1:]:
            # Time constraint: effect must occur after cause
            time_delta = effect.timestamp - cause.timestamp
            if time_delta <= 0 or time_delta > max_time_window_seconds:
                continue

            # Topological constraint: devices must be connected
            if cause.device_id == effect.device_id:
                # Same device: temporal ordering is strong evidence
                confidence = 0.8
                evidence = [
                    f"Same device ({cause.device_id})",
                    f"Temporal ordering ({time_delta:.1f}s apart)",
                ]
            elif topology_graph.has_node(cause.device_id) and topology_graph.has_node(effect.device_id):
                # Different devices: check if connected
                try:
                    path = nx.shortest_path(topology_graph, cause.device_id, effect.device_id)
                    path_length = len(path) - 1

                    if path_length == 1:
                        # Directly connected
                        confidence = 0.7
                        evidence = [
                            f"Directly connected devices",
                            f"Temporal ordering ({time_delta:.1f}s apart)",
                        ]
                    elif path_length <= 3:
                        # Close in topology
                        confidence = 0.5
                        evidence = [
                            f"{path_length}-hop path: {' → '.join(path)}",
                            f"Temporal ordering ({time_delta:.1f}s apart)",
                        ]
                    else:
                        # Distant in topology - weaker evidence
                        confidence = 0.3
                        evidence = [
                            f"{path_length}-hop path",
                            f"Temporal ordering ({time_delta:.1f}s apart)",
                        ]
                except nx.NetworkXNoPath:
                    # Not connected - unlikely to be causal
                    continue
            else:
                # Device not in topology - skip
                continue

            # Boost confidence if severity escalates
            severity_order = {"low": 1, "medium": 2, "high": 3}
            if severity_order.get(effect.severity, 1) > severity_order.get(cause.severity, 1):
                confidence = min(1.0, confidence + 0.1)
                evidence.append("Severity escalation")

            # Create causal edge
            edges.append(CausalEdge(
                cause_event=cause,
                effect_event=effect,
                confidence=confidence,
                evidence=evidence,
            ))

    return CausalGraph(events=sorted_events, edges=edges)


def identify_root_causes(
    causal_graph: CausalGraph,
    min_confidence: float = 0.5,
) -> list[RootCauseResult]:
    """Identify most likely root causes from causal graph.

    Args:
        causal_graph: Causal graph from build_causal_graph
        min_confidence: Minimum confidence for root cause candidates

    Returns:
        List of root cause results, sorted by confidence descending
    """
    root_candidates = causal_graph.get_root_candidates()
    results = []

    for root_event in root_candidates:
        downstream = causal_graph.get_downstream_events(root_event)
        affected_devices = list(set(e.device_id for e in downstream + [root_event]))
        impact_score = causal_graph.compute_impact_score(root_event)

        # Compute confidence based on:
        # 1. Impact (more downstream effects = higher confidence)
        # 2. Temporal ordering (earliest events more likely root)
        # 3. Edge confidence (average of outgoing edges)

        # Temporal factor: earlier events get higher confidence
        all_times = [e.timestamp for e in causal_graph.events]
        if all_times:
            time_range = max(all_times) - min(all_times)
            if time_range > 0:
                time_factor = 1.0 - ((root_event.timestamp - min(all_times)) / time_range)
            else:
                time_factor = 1.0
        else:
            time_factor = 0.5

        # Edge confidence factor
        outgoing_edges = [
            edge for edge in causal_graph.edges
            if edge.cause_event.event_id == root_event.event_id
        ]
        if outgoing_edges:
            avg_edge_confidence = sum(e.confidence for e in outgoing_edges) / len(outgoing_edges)
        else:
            avg_edge_confidence = 0.5

        # Impact factor: more affected devices = higher confidence
        impact_factor = min(1.0, len(affected_devices) / 5.0)

        # Weighted combination
        overall_confidence = (
            0.4 * time_factor +
            0.4 * avg_edge_confidence +
            0.2 * impact_factor
        )

        if overall_confidence < min_confidence:
            continue

        # Build evidence list
        evidence = [
            f"Earliest anomaly on {root_event.device_id}",
            f"Affects {len(affected_devices)} device(s): {', '.join(affected_devices)}",
        ]
        if downstream:
            evidence.append(f"{len(downstream)} downstream anomaly event(s)")

        # Build explanation
        explanation = (
            f"{root_event.device_id} {root_event.metric} {root_event.anomaly_type} "
            f"likely triggered cascading failures affecting {len(affected_devices)} devices. "
            f"Confidence: {overall_confidence:.0%}"
        )

        results.append(RootCauseResult(
            root_event=root_event,
            confidence=overall_confidence,
            impact_score=impact_score,
            affected_devices=affected_devices,
            affected_events=downstream,
            evidence=evidence,
            explanation=explanation,
        ))

    # Sort by confidence descending
    return sorted(results, key=lambda r: r.confidence, reverse=True)
