"""Tests for edge collector (consumer mode diagnostics)."""
import asyncio
import json

import pytest

from mcp_network.collectors.edge import EdgeCollector


def _run(coro):
    """Run async coroutine and return result."""
    return asyncio.run(coro)


class TestEdgeCollector:
    """Basic tests for edge collector functionality."""

    def setup_method(self):
        self.collector = EdgeCollector()

    def test_gateway_probe(self):
        """Test gateway probing."""
        result = _run(self.collector._probe_gateway())

        assert result.ip is not None
        assert result.latency_ms >= 0.0
        assert 0.0 <= result.loss_pct <= 100.0
        assert result.status in ("healthy", "degraded", "unreachable")

    def test_dns_probe(self):
        """Test DNS resolution timing."""
        result = _run(self.collector._probe_dns("google.com"))

        assert result.hostname == "google.com"
        assert result.resolution_ms >= 0.0
        # IP should be resolved or "unresolved"
        assert result.ip is not None

    def test_ping(self):
        """Test ping functionality."""
        # Ping a reliable target
        latency, loss = _run(self.collector._ping("8.8.8.8", count=3))

        assert latency >= 0.0
        assert 0.0 <= loss <= 100.0

    def test_traceroute(self):
        """Test traceroute collection."""
        # This may take a while
        hops = _run(self.collector._run_traceroute("8.8.8.8"))

        # Should get at least a few hops
        # (may be empty if traceroute/mtr not installed)
        assert isinstance(hops, list)

    def test_probe_destination_basic(self):
        """Test full destination probe."""
        # Use a reliable target
        probe = _run(self.collector.probe_destination("google.com"))

        assert probe.target == "google.com"
        assert probe.gateway is not None
        assert probe.gateway.status in ("healthy", "degraded", "unreachable")

        # DNS should have been probed
        assert probe.dns is not None
        assert probe.dns.hostname == "google.com"

        # Traceroute may be empty if tools not installed
        assert isinstance(probe.traceroute, list)

        assert probe.timestamp > 0


class TestEdgeTools:
    """Tests for edge diagnostic MCP tools."""

    def test_check_my_connection(self):
        """Test connection health check tool."""
        from mcp_network.tools import check_my_connection

        result_json = _run(check_my_connection())
        result = json.loads(result_json)

        assert "overall_status" in result
        assert "layers" in result
        assert "wifi" in result["layers"]
        assert "local_network" in result["layers"]
        assert "dns" in result["layers"]
        assert "internet" in result["layers"]

    def test_trace_path(self):
        """Test path tracing tool."""
        from mcp_network.tools import trace_path

        result_json = _run(trace_path("8.8.8.8"))
        result = json.loads(result_json)

        assert "destination" in result
        assert result["destination"] == "8.8.8.8"

        # Should have hops or an error
        assert "hops" in result or "error" in result

    def test_why_is_it_slow(self):
        """Test slowness diagnosis tool."""
        from mcp_network.tools import why_is_it_slow

        result_json = _run(why_is_it_slow("google.com"))
        result = json.loads(result_json)

        assert "destination" in result
        assert result["destination"] == "google.com"

        # Should have diagnosis or error
        assert "diagnosis" in result or "error" in result

        if "diagnosis" in result:
            assert "bottleneck" in result["diagnosis"]
            assert "confidence" in result["diagnosis"]
            assert "suggestions" in result
