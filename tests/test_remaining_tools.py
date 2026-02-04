"""
Tests for run_command, get_path, and get_device_status tools.

run_command: show-only guard, wrong-collector error, SSH path (mocked),
             unknown device.
get_path / get_device_status: exercised directly against the seeded
             simulated collector (same setup pattern as test_simulated_and_tools).
"""

import asyncio
import json
import random
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers (same pattern as test_simulated_and_tools)
# ---------------------------------------------------------------------------


def _fresh_collector():
    random.seed(42)
    import mcp_network.collectors.simulated as sim

    sim._collector = None
    collector = sim.SimulatedCollector()

    import mcp_network.collectors.config as cfg

    cfg._collector_instance = collector
    return collector


def _run(coro):
    return json.loads(asyncio.run(coro))


# ===========================================================================
# run_command
# ===========================================================================


class TestRunCommand:
    def setup_method(self):
        self._fresh = _fresh_collector()

    # -- show-only guard --

    def test_rejects_non_show_command(self):
        from mcp_network.tools import run_command

        result = _run(run_command("R1", "configure terminal"))
        assert "error" in result
        assert "read-only" in result["error"].lower() or "show" in result["error"].lower()

    def test_rejects_exec_command(self):
        from mcp_network.tools import run_command

        result = _run(run_command("R1", "reload"))
        assert "error" in result

    def test_rejects_empty_command(self):
        from mcp_network.tools import run_command

        result = _run(run_command("R1", "   "))
        assert "error" in result

    # -- wrong collector (simulated has no run_command method) --

    def test_simulated_collector_returns_error(self):
        from mcp_network.tools import run_command

        result = _run(run_command("R1", "show version"))
        assert "error" in result
        assert "ssh" in result["error"].lower() or "collector" in result["error"].lower()

    # -- SSH collector path (mocked) --

    def test_ssh_collector_happy_path(self):
        """Mock an SSH collector with run_command, wire it in, verify output."""
        mock_collector = MagicMock()
        mock_collector.run_command.return_value = "Cisco IOS-XE Software\n"

        import mcp_network.collectors.config as cfg

        cfg._collector_instance = mock_collector

        from mcp_network.tools import run_command

        result = _run(run_command("router-1", "show version"))
        assert result["device_id"] == "router-1"
        assert result["command"] == "show version"
        assert "Cisco IOS-XE" in result["output"]
        mock_collector.run_command.assert_called_once_with("router-1", "show version")

    def test_ssh_collector_unknown_device_error(self):
        """run_command on the SSH collector raises ValueError for unknown device."""
        mock_collector = MagicMock()
        mock_collector.run_command.side_effect = ValueError("Device 'R99' not found in topology")

        import mcp_network.collectors.config as cfg

        cfg._collector_instance = mock_collector

        from mcp_network.tools import run_command

        result = _run(run_command("R99", "show version"))
        assert "error" in result
        assert "R99" in result["error"]

    def test_show_command_case_insensitive(self):
        """'Show version' (capital S) should pass the guard."""
        mock_collector = MagicMock()
        mock_collector.run_command.return_value = "output"

        import mcp_network.collectors.config as cfg

        cfg._collector_instance = mock_collector

        from mcp_network.tools import run_command

        result = _run(run_command("R1", "Show version"))
        assert "output" in result


# ===========================================================================
# get_path
# ===========================================================================
# seed-42 shortest paths:
#   R1 → R10 : R1-R3-R5-R7-R9-R10   11.20 ms   5 hops
#   R1 → R2  : R1-R2                  2.1  ms   1 hop
# ===========================================================================


class TestGetPath:
    def setup_method(self):
        self._fresh = _fresh_collector()

    def test_happy_path_r1_r10(self):
        from mcp_network.tools import get_path

        result = _run(get_path("R1", "R10"))
        assert result["path"] == ["R1", "R3", "R5", "R7", "R9", "R10"]
        assert result["hop_count"] == 5
        assert result["total_latency_ms"] == 11.20

    def test_single_hop_r1_r2(self):
        from mcp_network.tools import get_path

        result = _run(get_path("R1", "R2"))
        assert result["path"] == ["R1", "R2"]
        assert result["hop_count"] == 1
        assert result["total_latency_ms"] == 2.1

    def test_hops_have_interface_names(self):
        from mcp_network.tools import get_path

        result = _run(get_path("R1", "R2"))
        hop = result["hops"][0]
        assert "from_interface" in hop
        assert "to_interface" in hop
        assert hop["from_device"] == "R1"
        assert hop["to_device"] == "R2"

    def test_unknown_destination_returns_error(self):
        from mcp_network.tools import get_path

        result = _run(get_path("R1", "R99"))
        assert "error" in result

    def test_unknown_source_returns_error(self):
        from mcp_network.tools import get_path

        result = _run(get_path("R99", "R1"))
        assert "error" in result

    def test_result_has_timestamp(self):
        from mcp_network.tools import get_path

        result = _run(get_path("R1", "R2"))
        assert "timestamp" in result


# ===========================================================================
# get_device_status
# ===========================================================================
# seed-42 devices:
#   R1  — healthy (cpu 63.5, all interfaces <80 util, <100 errors)
#   R3  — cpu congested (88.6), interfaces healthy
#   R4  — interfaces congested (all >80 util, >100 errors), cpu healthy
# ===========================================================================


class TestGetDeviceStatus:
    def setup_method(self):
        self._fresh = _fresh_collector()

    # -- healthy device --

    def test_healthy_device_no_issues(self):
        from mcp_network.tools import get_device_status

        result = _run(get_device_status("R1"))
        assert result["health_status"] == "healthy"
        assert result["issues"] == []

    def test_healthy_device_has_interfaces(self):
        from mcp_network.tools import get_device_status

        result = _run(get_device_status("R1"))
        assert len(result["interfaces"]) == 4

    def test_healthy_device_cpu_and_memory_present(self):
        from mcp_network.tools import get_device_status

        result = _run(get_device_status("R1"))
        assert "cpu_usage" in result
        assert "memory_usage" in result
        assert result["cpu_usage"] <= 80.0

    # -- cpu-congested device --

    def test_cpu_congested_device_flagged(self):
        from mcp_network.tools import get_device_status

        result = _run(get_device_status("R3"))
        assert result["health_status"] == "degraded"
        cpu_issues = [i for i in result["issues"] if i["type"] == "high_cpu"]
        assert len(cpu_issues) == 1
        assert cpu_issues[0]["value"] > 80

    def test_cpu_congested_no_interface_issues(self):
        from mcp_network.tools import get_device_status

        result = _run(get_device_status("R3"))
        iface_issues = [i for i in result["issues"] if i["type"] != "high_cpu"]
        assert iface_issues == []

    # -- interface-congested device --

    def test_interface_congested_device_flagged(self):
        from mcp_network.tools import get_device_status

        result = _run(get_device_status("R4"))
        assert result["health_status"] == "degraded"
        util_issues = [i for i in result["issues"] if i["type"] == "high_utilization"]
        err_issues = [i for i in result["issues"] if i["type"] == "high_errors"]
        assert len(util_issues) == 4  # all 4 interfaces
        assert len(err_issues) == 4

    def test_interface_congested_cpu_is_healthy(self):
        from mcp_network.tools import get_device_status

        result = _run(get_device_status("R4"))
        cpu_issues = [i for i in result["issues"] if i["type"] == "high_cpu"]
        assert cpu_issues == []

    # -- unknown device --

    def test_unknown_device_returns_error(self):
        from mcp_network.tools import get_device_status

        result = _run(get_device_status("R99"))
        assert "error" in result
        assert "available_devices" in result
