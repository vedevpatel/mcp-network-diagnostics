"""
Parsers for Cisco IOS-XR CLI output.

These parsers extract structured data from show command output.
"""

import re
from typing import Dict, List


def parse_memory_summary(output: str) -> Dict[str, float]:
    """
    Parse 'show memory summary' output.

    Args:
        output: Raw command output

    Returns:
        Dictionary with memory statistics:
        - total_mb: Total physical memory in MB
        - available_mb: Available physical memory in MB
        - used_percent: Memory utilization percentage

    Example output:
        Physical Memory: 3071M total (1436M available)
        Application Memory : 2868M (1436M available)
        Image: 244M (bootram: 39M)
        Reserved: 205M, IPC: 133M, Stack: 72M
        Total shared memory:  47M (64 segments)
    """
    result = {
        "total_mb": 0.0,
        "available_mb": 0.0,
        "used_percent": 0.0,
    }

    # Parse: Physical Memory: 3071M total (1436M available)
    physical_match = re.search(
        r'Physical Memory:\s+(\d+)M\s+total\s+\((\d+)M\s+available\)',
        output
    )

    if physical_match:
        total = float(physical_match.group(1))
        available = float(physical_match.group(2))
        used = total - available

        result["total_mb"] = total
        result["available_mb"] = available
        result["used_percent"] = (used / total) * 100 if total > 0 else 0.0

    return result


def parse_interface_brief(output: str) -> List[Dict[str, str]]:
    """
    Parse 'show ip interface brief' output.

    Args:
        output: Raw command output

    Returns:
        List of interface dictionaries with:
        - name: Interface name
        - ip_address: IP address or "unassigned"
        - status: Admin status (Up/Shutdown)
        - protocol: Protocol status (Up/Down)
        - vrf: VRF name

    Example output:
        Interface                      IP-Address      Status          Protocol Vrf-Name
        Loopback0                      1.1.1.1         Up              Up       default
        MgmtEth0/RP0/CPU0/0            10.10.20.175    Up              Up       default
        GigabitEthernet0/0/0/0         unassigned      Shutdown        Down     default
    """
    interfaces = []

    # Skip header line
    lines = output.strip().split('\n')
    for line in lines[1:]:  # Skip first line (header)
        # Parse fixed-width columns
        # Interface name can be long, IP is ~15 chars, Status ~16, Protocol ~13, VRF ~8
        match = re.match(
            r'(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)',
            line.strip()
        )

        if match:
            interfaces.append({
                "name": match.group(1),
                "ip_address": match.group(2),
                "status": match.group(3),
                "protocol": match.group(4),
                "vrf": match.group(5),
            })

    return interfaces


def parse_interface_detail(output: str) -> Dict[str, any]:
    """
    Parse 'show interfaces <name>' output for detailed interface stats.

    Args:
        output: Raw command output

    Returns:
        Dictionary with interface details:
        - name: Interface name
        - admin_status: Admin status (Up/Shutdown)
        - protocol_status: Protocol status (Up/Down)
        - hardware_address: MAC address
        - mtu: MTU in bytes
        - bandwidth_kbit: Bandwidth in Kbit
        - input_rate_bps: Input rate in bits/sec (5 minute average)
        - output_rate_bps: Output rate in bits/sec (5 minute average)
        - input_packets: Total input packets
        - output_packets: Total output packets
        - input_errors: Total input errors
        - output_errors: Total output errors
        - utilization_percent: Estimated utilization based on bandwidth

    Example output:
        GigabitEthernet0/0/0/0 is Shutdown, line protocol is Down
          Interface state transitions: 1
          Hardware is GigabitEthernet, address is 5254.00ff.3802 (bia 5254.00ff.3802)
          MTU 1514 bytes, BW 1000000 Kbit (Max: 1000000 Kbit)
          5 minute input rate 0 bits/sec, 0 packets/sec
          5 minute output rate 0 bits/sec, 0 packets/sec
          0 input errors, 0 CRC, 0 frame, 0 overrun, 0 ignored, 0 abort
          0 output errors, 0 underruns, 0 applique, 0 resets
    """
    result = {
        "name": "",
        "admin_status": "unknown",
        "protocol_status": "unknown",
        "hardware_address": "",
        "mtu": 0,
        "bandwidth_kbit": 0,
        "input_rate_bps": 0,
        "output_rate_bps": 0,
        "input_packets": 0,
        "output_packets": 0,
        "input_errors": 0,
        "output_errors": 0,
        "utilization_percent": 0.0,
    }

    # Parse first line: GigabitEthernet0/0/0/0 is Shutdown, line protocol is Down
    first_line_match = re.search(
        r'(\S+)\s+is\s+(\w+),\s+line protocol is\s+(\w+)',
        output
    )
    if first_line_match:
        result["name"] = first_line_match.group(1)
        result["admin_status"] = first_line_match.group(2)
        result["protocol_status"] = first_line_match.group(3)

    # Parse hardware address: address is 5254.00ff.3802
    hw_match = re.search(r'address is\s+([\da-f.]+)', output, re.IGNORECASE)
    if hw_match:
        result["hardware_address"] = hw_match.group(1)

    # Parse MTU and bandwidth: MTU 1514 bytes, BW 1000000 Kbit
    mtu_bw_match = re.search(r'MTU\s+(\d+)\s+bytes,\s+BW\s+(\d+)\s+Kbit', output)
    if mtu_bw_match:
        result["mtu"] = int(mtu_bw_match.group(1))
        result["bandwidth_kbit"] = int(mtu_bw_match.group(2))

    # Parse input rate: 5 minute input rate 0 bits/sec, 0 packets/sec
    input_rate_match = re.search(r'5 minute input rate\s+(\d+)\s+bits/sec', output)
    if input_rate_match:
        result["input_rate_bps"] = int(input_rate_match.group(1))

    # Parse output rate: 5 minute output rate 0 bits/sec, 0 packets/sec
    output_rate_match = re.search(r'5 minute output rate\s+(\d+)\s+bits/sec', output)
    if output_rate_match:
        result["output_rate_bps"] = int(output_rate_match.group(1))

    # Parse packet counts: 0 packets input, 0 bytes, 0 total input drops
    input_packets_match = re.search(r'(\d+)\s+packets input', output)
    if input_packets_match:
        result["input_packets"] = int(input_packets_match.group(1))

    # Parse output packets: 0 packets output, 0 bytes, 0 total output drops
    output_packets_match = re.search(r'(\d+)\s+packets output', output)
    if output_packets_match:
        result["output_packets"] = int(output_packets_match.group(1))

    # Parse input errors: 0 input errors, 0 CRC, 0 frame...
    input_errors_match = re.search(r'(\d+)\s+input errors', output)
    if input_errors_match:
        result["input_errors"] = int(input_errors_match.group(1))

    # Parse output errors: 0 output errors, 0 underruns...
    output_errors_match = re.search(r'(\d+)\s+output errors', output)
    if output_errors_match:
        result["output_errors"] = int(output_errors_match.group(1))

    # Calculate utilization percentage
    # Utilization = (input_rate + output_rate) / bandwidth * 100
    if result["bandwidth_kbit"] > 0:
        bandwidth_bps = result["bandwidth_kbit"] * 1000  # Convert Kbit to bps
        total_rate = result["input_rate_bps"] + result["output_rate_bps"]
        result["utilization_percent"] = (total_rate / bandwidth_bps) * 100

    return result
