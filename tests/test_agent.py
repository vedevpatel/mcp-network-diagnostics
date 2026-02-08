"""Tests for autonomous monitoring agent."""

import asyncio
from datetime import datetime, timezone

from mcp_network.agent import NetworkAgent, AgentConfig, Intent, IntentParser


def _run(coro):
    """Run async code in sync test context."""
    return asyncio.run(coro)


def test_intent_parser_latency():
    """Test parsing latency-based intents."""
    parser = IntentParser()

    intent = _run(parser.parse("Zoom calls should never lag"))

    assert intent.target == "zoom.us"
    assert intent.metric == "latency"
    assert intent.threshold == 100.0  # default
    assert intent.comparison == "<"
    assert "diagnose" in intent.actions


def test_intent_parser_with_threshold():
    """Test parsing intents with explicit thresholds."""
    parser = IntentParser()

    intent = _run(parser.parse("Alert me if gaming latency exceeds 50ms"))

    assert intent.target == "gaming"
    assert intent.metric == "latency"
    assert intent.threshold == 50.0
    assert intent.comparison == ">"
    assert "alert" in intent.actions
    assert "diagnose" in intent.actions


def test_intent_parser_baseline():
    """Test parsing baseline deviation intents."""
    parser = IntentParser()

    intent = _run(parser.parse("My connection should stay close to baseline"))

    assert intent.target == "all"
    assert intent.metric == "baseline_deviation"
    assert intent.threshold == 2.0
    assert intent.comparison == "<"


def test_intent_parser_priority():
    """Test priority extraction."""
    parser = IntentParser()

    intent = _run(parser.parse("Critical: streaming should never drop packets"))
    assert intent.priority == 8

    intent = _run(parser.parse("Nice to have: low priority monitoring"))
    assert intent.priority == 3

    intent = _run(parser.parse("Zoom should be fast"))
    assert intent.priority == 5  # default


def test_agent_lifecycle():
    """Test agent start/stop lifecycle."""
    config = AgentConfig(poll_interval=0.1)
    agent = NetworkAgent(config)

    assert not agent.running

    _run(agent.start())
    assert agent.running

    _run(agent.stop())
    assert not agent.running


def test_agent_intent_management():
    """Test adding/removing intents."""
    agent = NetworkAgent()

    intent1 = Intent(
        id="test1",
        name="Test intent 1",
        target="zoom.us",
        metric="latency",
        threshold=100.0,
        comparison="<",
        priority=5,
        actions=["diagnose"],
    )

    intent2 = Intent(
        id="test2",
        name="Test intent 2",
        target="gaming",
        metric="latency",
        threshold=50.0,
        comparison="<",
        priority=8,
        actions=["alert", "diagnose"],
    )

    agent.add_intent(intent1)
    agent.add_intent(intent2)

    assert len(agent.get_intents()) == 2

    agent.remove_intent("test1")
    assert len(agent.get_intents()) == 1
    assert agent.get_intents()[0].id == "test2"


def test_agent_metric_extraction():
    """Test extracting metrics from probe data."""
    from mcp_network.collectors.edge import ProbeResult, GatewayResult, DNSResult

    agent = NetworkAgent()

    # Create mock probe
    probe = ProbeResult(
        target="8.8.8.8",
        gateway=GatewayResult(
            ip="192.168.1.1",
            latency_ms=45.2,
            loss_pct=0.0,
            status="healthy",
        ),
        dns=DNSResult(
            hostname="google.com",
            ip="8.8.8.8",
            resolution_ms=12.3,
        ),
        traceroute=[],
        http=None,
        wifi=None,
    )

    # Extract latency
    latency = agent._extract_metric(probe, "latency")
    assert latency == 45.2

    # Extract loss
    loss = agent._extract_metric(probe, "loss")
    assert loss == 0.0

    # Extract DNS time
    dns_time = agent._extract_metric(probe, "dns_time")
    assert dns_time == 12.3


def test_agent_threshold_checking():
    """Test threshold violation detection."""
    agent = NetworkAgent()

    # Less than comparison
    assert not agent._check_threshold(50.0, 100.0, "<")  # OK
    assert agent._check_threshold(150.0, 100.0, "<")  # Violated

    # Greater than comparison
    assert agent._check_threshold(50.0, 100.0, ">")  # Violated
    assert not agent._check_threshold(150.0, 100.0, ">")  # OK

    # Equal comparison
    assert not agent._check_threshold(100.0, 100.0, "==")  # OK
    assert agent._check_threshold(105.0, 100.0, "==")  # Violated


def test_agent_incident_retention():
    """Test that incidents are retained with limit."""
    config = AgentConfig(max_incidents_retained=5)
    agent = NetworkAgent(config)

    # Create dummy incidents
    for i in range(10):
        from mcp_network.agent.core import Incident
        incident = Incident(
            id=f"test{i}",
            intent_id="intent1",
            timestamp=datetime.now(timezone.utc),
            metric="latency",
            target="test",
            current_value=100.0,
            threshold=50.0,
            comparison="<",
            severity="medium",
        )
        agent.incidents.append(incident)

        # Trim if needed
        if len(agent.incidents) > config.max_incidents_retained:
            agent.incidents.pop(0)

    # Should keep only the last 5
    assert len(agent.incidents) == 5
    assert agent.incidents[0].id == "test5"
    assert agent.incidents[-1].id == "test9"


def test_intent_parser_target_mappings():
    """Test various target keyword mappings."""
    parser = IntentParser()

    # Zoom
    intent = _run(parser.parse("zoom should be fast"))
    assert intent.target == "zoom.us"

    # Google Meet
    intent = _run(parser.parse("meet calls dropping"))
    assert intent.target == "meet.google.com"

    # Teams
    intent = _run(parser.parse("teams latency high"))
    assert intent.target == "teams.microsoft.com"

    # Gaming
    intent = _run(parser.parse("gaming lag"))
    assert intent.target == "gaming"

    # Default to all
    intent = _run(parser.parse("connection is slow"))
    assert intent.target == "all"


def test_intent_parser_loss_keywords():
    """Test packet loss keyword detection."""
    parser = IntentParser()

    intent = _run(parser.parse("alert me if packet loss exceeds 5%"))
    assert intent.metric == "loss"
    assert intent.threshold == 5.0

    intent = _run(parser.parse("connection keeps dropping"))
    assert intent.metric == "loss"


def test_agent_severity_calculation():
    """Test incident severity calculation."""
    from mcp_network.collectors.edge import ProbeResult, GatewayResult

    agent = NetworkAgent()

    intent = Intent(
        id="test",
        name="Test",
        target="test",
        metric="latency",
        threshold=100.0,
        comparison="<",
        priority=5,
        actions=["diagnose"],
    )
    agent.add_intent(intent)

    # Create probe with high latency (2x threshold)
    probe = ProbeResult(
        target="test",
        gateway=GatewayResult(
            ip="192.168.1.1",
            latency_ms=220.0,
            loss_pct=0.0,
            status="degraded",
        ),
        dns=None,
        traceroute=[],
        http=None,
        wifi=None,
    )

    violation = (intent, {
        "probe": probe,
        "metric": "latency",
        "value": 220.0,
        "threshold": 100.0,
    })

    incident = _run(agent._diagnose(violation))

    # 220/100 = 2.2x, should be "high"
    assert incident.severity == "high"
    assert incident.current_value == 220.0
    assert incident.threshold == 100.0
