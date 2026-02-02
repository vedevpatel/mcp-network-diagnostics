"""
Unit tests for IOS-XR parsers.
"""

import os
import pytest
from mcp_network.parsers.iosxr import (
    parse_memory_summary,
    parse_interface_brief,
    parse_interface_detail,
)


# Get path to test fixtures
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "iosxr")


def load_fixture(filename: str) -> str:
    """
    Load the test fixture file.
    Args:
        filename (str): Name of the fixture file.
    Returns:
        str: Contents of the fixture file.
    """
    path = os.path.join(FIXTURES_DIR, filename)
    with open(path, 'r') as f:
        return f.read()


def test_parse_memory_summary():
    """
    Test parsing show memory summary output.
    """
    output = load_fixture("show_memory_summary.txt")
    result = parse_memory_summary(output)

    assert result["total_mb"] == 3071
    assert result["available_mb"] == 1436
    # Used = 3071 - 1436 = 1635
    # Used % = (1635 / 3071) * 100 = 53.24%
    assert 53.0 < result["used_percent"] < 54.0


def test_parse_interface_brief():
    """
    Test parsing show ip interface brief output.
    """
    output = load_fixture("show_ip_interface_brief.txt")
    interfaces = parse_interface_brief(output)

    assert len(interfaces) == 4

    # Check Loopback0
    loopback = interfaces[0]
    assert loopback["name"] == "Loopback0"
    assert loopback["ip_address"] == "1.1.1.1"
    assert loopback["status"] == "Up"
    assert loopback["protocol"] == "Up"
    assert loopback["vrf"] == "default"

    # Check GigabitEthernet0/0/0/0
    gig0 = interfaces[2]
    assert gig0["name"] == "GigabitEthernet0/0/0/0"
    assert gig0["ip_address"] == "unassigned"
    assert gig0["status"] == "Shutdown"
    assert gig0["protocol"] == "Down"
    assert gig0["vrf"] == "default"


def test_parse_interface_detail():
    """
    Test parsing show interfaces <name> output.
    """
    output = load_fixture("show_interfaces_gigabitethernet.txt")
    result = parse_interface_detail(output)

    # Basic info
    assert result["name"] == "GigabitEthernet0/0/0/0"
    assert result["admin_status"] == "Shutdown"
    assert result["protocol_status"] == "Down"

    # Hardware
    assert result["hardware_address"] == "5254.00ff.3802"
    assert result["mtu"] == 1514
    assert result["bandwidth_kbit"] == 1000000

    # Rates (all zero for shutdown interface)
    assert result["input_rate_bps"] == 0
    assert result["output_rate_bps"] == 0

    # Packets
    assert result["input_packets"] == 0
    assert result["output_packets"] == 0

    # Errors
    assert result["input_errors"] == 0
    assert result["output_errors"] == 0

    # Utilization
    assert result["utilization_percent"] == 0.0


def test_parse_memory_summary_missing_data():
    """
    Test parser handles malformed output gracefully.
    """
    output = "Invalid output"
    result = parse_memory_summary(output)

    assert result["total_mb"] == 0.0
    assert result["available_mb"] == 0.0
    assert result["used_percent"] == 0.0


def test_parse_interface_brief_empty():
    """Test parser handles empty output."""
    output = "Interface                      IP-Address      Status          Protocol Vrf-Name\n"
    interfaces = parse_interface_brief(output)

    assert len(interfaces) == 0


def test_parse_interface_detail_with_traffic():
    """
    Test parser calculates utilization correctly with traffic.
    """

    output = """GigabitEthernet0/0/0/1 is Up, line protocol is Up
  Hardware is GigabitEthernet, address is 5254.00ff.3803
  MTU 1514 bytes, BW 1000000 Kbit (Max: 1000000 Kbit)
  5 minute input rate 250000000 bits/sec, 30000 packets/sec
  5 minute output rate 250000000 bits/sec, 30000 packets/sec
     1000000 packets input, 1500000000 bytes, 0 total input drops
     1000000 packets output, 1500000000 bytes, 0 total output drops
     5 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored, 0 abort
     3 output errors, 0 underruns, 0 applique, 0 resets
"""

    result = parse_interface_detail(output)

    assert result["name"] == "GigabitEthernet0/0/0/1"
    assert result["admin_status"] == "Up"
    assert result["protocol_status"] == "Up"
    assert result["bandwidth_kbit"] == 1000000

    # Input rate: 250,000,000 bps
    assert result["input_rate_bps"] == 250000000

    # Output rate: 250,000,000 bps
    assert result["output_rate_bps"] == 250000000

    # Utilization: (250M + 250M) / (1000M) * 100 = 50%
    assert 49.0 < result["utilization_percent"] < 51.0

    # Packet counts
    assert result["input_packets"] == 1000000
    assert result["output_packets"] == 1000000

    # Errors
    assert result["input_errors"] == 5
    assert result["output_errors"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
