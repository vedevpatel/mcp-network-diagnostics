"""
Unit tests for IOSXRCollector with mocked SSH connections.
"""

import os
import pytest
import tempfile
import yaml
from unittest.mock import patch, MagicMock
from mcp_network.collectors.iosxr import IOSXRCollector


# Path to shared fixtures
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "iosxr")


def load_fixture(filename: str) -> str:
    with open(os.path.join(FIXTURES_DIR, filename), 'r') as f:
        return f.read()


# Pre-load fixture content
MEMORY_OUTPUT = load_fixture("show_memory_summary.txt")
IFACE_BRIEF_OUTPUT = load_fixture("show_ip_interface_brief.txt")
IFACE_DETAIL_OUTPUT = load_fixture("show_interfaces_gigabitethernet.txt")


def _topology_yaml(devices=None, links=None):
    """Write a temporary topology YAML and return its path."""
    if devices is None:
        devices = [{
            "id": "router-1",
            "type": "router",
            "host": "10.0.0.1",
            "username": "admin",
            "password": "secret",
            "port": 22,
        }]
    if links is None:
        links = []

    data = {"devices": devices, "links": links}
    tmp = tempfile.NamedTemporaryFile(
        mode='w', suffix='.yaml', delete=False
    )
    yaml.dump(data, tmp)
    tmp.close()
    return tmp.name


def _mock_send_command(command: str) -> str:
    """Route show commands to fixture files."""
    if command.startswith("show memory summary"):
        return MEMORY_OUTPUT
    elif command.startswith("show ip interface brief"):
        return IFACE_BRIEF_OUTPUT
    elif command.startswith("show interfaces"):
        return IFACE_DETAIL_OUTPUT
    return ""


@patch("mcp_network.collectors.iosxr.ConnectHandler")
class TestIOSXRCollectorBasic:
    """Tests for IOSXRCollector with a single successfully connected device."""

    def _make_collector(self, mock_connect_handler, topo_file):
        mock_conn = MagicMock()
        mock_conn.send_command.side_effect = _mock_send_command
        mock_connect_handler.return_value = mock_conn
        return IOSXRCollector(topology_file=topo_file)

    def test_single_device_populated(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [{"id": "R1", "type": "router", "host": "10.0.0.1",
                         "username": "admin", "password": "secret"}],
            "links": [],
        }))

        collector = self._make_collector(mock_connect_handler, str(topo))

        assert "R1" in collector.devices
        device = collector.devices["R1"]
        assert device.device_id == "R1"
        assert device.device_type == "router"

    def test_memory_usage_parsed(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [{"id": "R1", "type": "router", "host": "10.0.0.1",
                         "username": "admin", "password": "secret"}],
            "links": [],
        }))

        collector = self._make_collector(mock_connect_handler, str(topo))
        device = collector.devices["R1"]

        # From fixture: 3071M total, 1436M available → used% = (3071-1436)/3071*100 ≈ 53.24
        assert 53.0 < device.memory_usage < 54.0

    def test_cpu_defaults_to_50(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [{"id": "R1", "type": "router", "host": "10.0.0.1",
                         "username": "admin", "password": "secret"}],
            "links": [],
        }))

        collector = self._make_collector(mock_connect_handler, str(topo))
        # IOS-XR collector has no easy CPU metric; defaults to 50.0
        assert collector.devices["R1"].cpu_usage == 50.0

    def test_interfaces_count(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [{"id": "R1", "type": "router", "host": "10.0.0.1",
                         "username": "admin", "password": "secret"}],
            "links": [],
        }))

        collector = self._make_collector(mock_connect_handler, str(topo))
        device = collector.devices["R1"]

        # brief fixture has 4 interfaces: Loopback0, MgmtEth0/RP0/CPU0/0,
        # GigabitEthernet0/0/0/0, GigabitEthernet0/0/0/1
        assert len(device.interfaces) == 4

    def test_interface_names(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [{"id": "R1", "type": "router", "host": "10.0.0.1",
                         "username": "admin", "password": "secret"}],
            "links": [],
        }))

        collector = self._make_collector(mock_connect_handler, str(topo))
        names = [iface.name for iface in collector.devices["R1"].interfaces]

        assert "Loopback0" in names
        assert "MgmtEth0/RP0/CPU0/0" in names
        assert "GigabitEthernet0/0/0/0" in names
        assert "GigabitEthernet0/0/0/1" in names

    def test_interface_status_lowercased(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [{"id": "R1", "type": "router", "host": "10.0.0.1",
                         "username": "admin", "password": "secret"}],
            "links": [],
        }))

        collector = self._make_collector(mock_connect_handler, str(topo))
        statuses = {iface.name: iface.status for iface in collector.devices["R1"].interfaces}

        # brief fixture: Loopback0 is "Up", GigabitEthernet0/0/0/0 is "Shutdown"
        assert statuses["Loopback0"] == "up"
        assert statuses["GigabitEthernet0/0/0/0"] == "shutdown"

    def test_interface_utilization_zero_for_shutdown(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [{"id": "R1", "type": "router", "host": "10.0.0.1",
                         "username": "admin", "password": "secret"}],
            "links": [],
        }))

        collector = self._make_collector(mock_connect_handler, str(topo))
        # detail fixture is all zeros (shutdown interface)
        for iface in collector.devices["R1"].interfaces:
            assert iface.utilization == 0.0
            assert iface.errors == 0

    def test_graph_has_device_node(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [{"id": "R1", "type": "router", "host": "10.0.0.1",
                         "username": "admin", "password": "secret"}],
            "links": [],
        }))

        collector = self._make_collector(mock_connect_handler, str(topo))
        assert "R1" in collector.graph.nodes

    def test_ssh_called_with_correct_params(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [{"id": "R1", "type": "router", "host": "10.0.0.1",
                         "username": "testuser", "password": "testpass", "port": 2222}],
            "links": [],
        }))

        self._make_collector(mock_connect_handler, str(topo))

        mock_connect_handler.assert_called_once()
        call_kwargs = mock_connect_handler.call_args[1]
        assert call_kwargs["device_type"] == "cisco_xr"
        assert call_kwargs["host"] == "10.0.0.1"
        assert call_kwargs["username"] == "testuser"
        assert call_kwargs["password"] == "testpass"
        assert call_kwargs["port"] == 2222

    def test_disconnect_called(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [{"id": "R1", "type": "router", "host": "10.0.0.1",
                         "username": "admin", "password": "secret"}],
            "links": [],
        }))

        mock_conn = MagicMock()
        mock_conn.send_command.side_effect = _mock_send_command
        mock_connect_handler.return_value = mock_conn

        IOSXRCollector(topology_file=str(topo))
        mock_conn.disconnect.assert_called_once()


@patch("mcp_network.collectors.iosxr.ConnectHandler")
class TestIOSXRCollectorConnectionFailure:
    """Tests for device connection failures."""

    def test_connection_failure_skips_device(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [{"id": "R1", "type": "router", "host": "10.0.0.1",
                         "username": "admin", "password": "secret"}],
            "links": [],
        }))

        # ConnectHandler raises → _connect_device returns None
        mock_connect_handler.side_effect = Exception("Connection refused")

        collector = IOSXRCollector(topology_file=str(topo))

        assert len(collector.devices) == 0
        assert "R1" not in collector.graph.nodes

    def test_partial_failure_keeps_reachable_device(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [
                {"id": "R1", "type": "router", "host": "10.0.0.1",
                 "username": "admin", "password": "secret"},
                {"id": "R2", "type": "router", "host": "10.0.0.2",
                 "username": "admin", "password": "secret"},
            ],
            "links": [],
        }))

        good_conn = MagicMock()
        good_conn.send_command.side_effect = _mock_send_command

        # First call (R1) fails, second call (R2) succeeds
        mock_connect_handler.side_effect = [
            Exception("Connection refused"),
            good_conn,
        ]

        collector = IOSXRCollector(topology_file=str(topo))

        assert "R1" not in collector.devices
        assert "R2" in collector.devices
        assert "R2" in collector.graph.nodes


@patch("mcp_network.collectors.iosxr.ConnectHandler")
class TestIOSXRCollectorLinks:
    """Tests for link building and graph edges."""

    def _setup(self, mock_connect_handler):
        mock_conn = MagicMock()
        mock_conn.send_command.side_effect = _mock_send_command
        mock_connect_handler.return_value = mock_conn

    def test_links_populated(self, mock_connect_handler, tmp_path):
        self._setup(mock_connect_handler)
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [
                {"id": "R1", "type": "router", "host": "10.0.0.1",
                 "username": "admin", "password": "secret"},
                {"id": "R2", "type": "router", "host": "10.0.0.2",
                 "username": "admin", "password": "secret"},
            ],
            "links": [{
                "src_device": "R1",
                "src_interface": "GigabitEthernet0/0/0/0",
                "dst_device": "R2",
                "dst_interface": "GigabitEthernet0/0/0/0",
                "default_latency_ms": 5.0,
            }],
        }))

        collector = IOSXRCollector(topology_file=str(topo))

        assert len(collector.links) == 1
        link = collector.links[0]
        assert link.src_device == "R1"
        assert link.dst_device == "R2"
        assert link.latency_ms == 5.0

    def test_graph_edge_created(self, mock_connect_handler, tmp_path):
        self._setup(mock_connect_handler)
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [
                {"id": "R1", "type": "router", "host": "10.0.0.1",
                 "username": "admin", "password": "secret"},
                {"id": "R2", "type": "router", "host": "10.0.0.2",
                 "username": "admin", "password": "secret"},
            ],
            "links": [{
                "src_device": "R1",
                "src_interface": "GigabitEthernet0/0/0/0",
                "dst_device": "R2",
                "dst_interface": "GigabitEthernet0/0/0/0",
                "default_latency_ms": 3.5,
            }],
        }))

        collector = IOSXRCollector(topology_file=str(topo))

        assert collector.graph.has_edge("R1", "R2")
        edge_data = collector.graph.edges["R1", "R2"]
        assert edge_data["latency"] == 3.5
        assert edge_data["src_interface"] == "GigabitEthernet0/0/0/0"
        assert edge_data["dst_interface"] == "GigabitEthernet0/0/0/0"

    def test_link_default_latency_when_missing(self, mock_connect_handler, tmp_path):
        self._setup(mock_connect_handler)
        topo = tmp_path / "topo.yaml"
        topo.write_text(yaml.dump({
            "devices": [
                {"id": "R1", "type": "router", "host": "10.0.0.1",
                 "username": "admin", "password": "secret"},
                {"id": "R2", "type": "router", "host": "10.0.0.2",
                 "username": "admin", "password": "secret"},
            ],
            "links": [{
                "src_device": "R1",
                "src_interface": "GigabitEthernet0/0/0/0",
                "dst_device": "R2",
                "dst_interface": "GigabitEthernet0/0/0/0",
                # no default_latency_ms key
            }],
        }))

        collector = IOSXRCollector(topology_file=str(topo))

        # _build_link defaults to 2.0 when key is missing
        assert collector.links[0].latency_ms == 2.0


@patch("mcp_network.collectors.iosxr.ConnectHandler")
class TestIOSXRCollectorTopologyErrors:
    """Tests for topology file loading errors."""

    def test_missing_topology_file_raises(self, mock_connect_handler):
        with pytest.raises(FileNotFoundError):
            IOSXRCollector(topology_file="/nonexistent/path/topo.yaml")

    def test_invalid_yaml_raises(self, mock_connect_handler, tmp_path):
        topo = tmp_path / "bad.yaml"
        topo.write_text("devices: [[[invalid yaml{{{{")

        with pytest.raises(Exception):
            IOSXRCollector(topology_file=str(topo))
