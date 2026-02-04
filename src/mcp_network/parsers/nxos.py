"""
Parsers for Cisco NX-OS CLI output (Nexus 9000, 7000, etc.).
"""

import re
from typing import Dict, List


def parse_system_resources(output: str) -> Dict[str, float]:
    """
    Parse 'show system resources' output.

    Returns both CPU and memory from a single command output.
    CPU is derived from the aggregate 'CPU states' line (100 - idle%).
    Memory values are in kilobytes in the raw output.

    Returns:
        Dict with 'cpu_percent', 'total_kb', 'used_kb', 'free_kb', 'memory_percent'
    """
    result = {
        "cpu_percent": 0.0,
        "total_kb": 0,
        "used_kb": 0,
        "free_kb": 0,
        "memory_percent": 0.0,
    }

    # CPU: aggregate line (flush left, not indented per-core lines)
    # "CPU states  :   0.0% user,   0.2% kernel,   99.8% idle"
    cpu_match = re.search(
        r'^CPU states\s*:\s*[\d.]+% user,\s*[\d.]+% kernel,\s*([\d.]+)% idle',
        output,
        re.MULTILINE
    )
    if cpu_match:
        idle = float(cpu_match.group(1))
        result["cpu_percent"] = round(100.0 - idle, 1)

    # Memory: "Memory usage:   16402560K total,   2664308K used,   13738252K free"
    mem_match = re.search(
        r'Memory usage:\s*(\d+)K\s+total,\s*(\d+)K\s+used,\s*(\d+)K\s+free',
        output
    )
    if mem_match:
        total_kb = int(mem_match.group(1))
        used_kb = int(mem_match.group(2))
        free_kb = int(mem_match.group(3))
        result["total_kb"] = total_kb
        result["used_kb"] = used_kb
        result["free_kb"] = free_kb
        if total_kb > 0:
            result["memory_percent"] = round((used_kb / total_kb) * 100, 1)

    return result


def parse_interface_brief(output: str) -> List[Dict[str, str]]:
    """
    Parse 'show interface brief' output.

    NX-OS format columns: Interface, VLAN, Type, Mode, Status, Reason, Speed, Port-ch
    Interface names are abbreviated (Eth1/1).  Status is 'up' or 'down'.

    Returns:
        List of dicts with 'name', 'status', 'speed', 'reason'
    """
    interfaces = []

    for line in output.strip().split('\n'):
        # Skip headers, separator lines, empty lines
        if not line.strip():
            continue
        if line.startswith('-'):
            continue
        if 'Ethernet' in line and 'VLAN' in line:
            continue
        if 'Interface' in line and 'Status' in line:
            continue

        # Match interface lines: Eth1/1 or Eth1/1/1 at the start
        parts = line.split()
        if len(parts) < 5:
            continue
        if not parts[0].startswith('Eth'):
            continue

        name = parts[0]
        # Status is at index 4 in the standard layout
        status = parts[4].lower()

        # Speed field: find the entry that matches patterns like "10G(D)", "1G(D)", "auto(D)"
        speed = ""
        reason = "none"
        for i, part in enumerate(parts):
            if re.match(r'[\d.]+[GMg]\(', part) or part.startswith('auto('):
                speed = part
                # Reason is everything between status (index 4) and speed
                reason_parts = parts[5:i]
                if reason_parts:
                    reason = " ".join(reason_parts)
                break

        interfaces.append({
            "name": name,
            "status": status,
            "speed": speed,
            "reason": reason,
        })

    return interfaces


def parse_interface_detail(output: str) -> Dict[str, any]:
    """
    Parse 'show interface Ethernet<x>' output.

    NX-OS uses 30-second rate averages by default and singular
    'input error' / 'output error' (no trailing 's').

    Returns:
        Dict with 'name', 'admin_status', 'bandwidth_kbit',
        'input_rate_bps', 'output_rate_bps',
        'input_errors', 'output_errors', 'utilization_percent'
    """
    result = {
        "name": "",
        "admin_status": "down",
        "bandwidth_kbit": 0,
        "input_rate_bps": 0,
        "output_rate_bps": 0,
        "input_errors": 0,
        "output_errors": 0,
        "utilization_percent": 0.0,
    }

    # Name and operational status: "Ethernet1/1 is up"
    name_match = re.match(r'(\S+)\s+is\s+(up|down)', output.strip())
    if name_match:
        result["name"] = name_match.group(1)

    # Admin status: "admin state is up,"
    admin_match = re.search(r'admin state is\s+(\w+)', output)
    if admin_match:
        result["admin_status"] = admin_match.group(1).lower()

    # Bandwidth: "BW 10000000 Kbit"
    bw_match = re.search(r'BW\s+(\d+)\s+Kbit', output)
    if bw_match:
        result["bandwidth_kbit"] = int(bw_match.group(1))

    # Rates: NX-OS uses "30 seconds input rate X bits/sec"
    input_match = re.search(r'30 seconds input rate\s+(\d+)\s+bits/sec', output)
    if input_match:
        result["input_rate_bps"] = int(input_match.group(1))

    output_match = re.search(r'30 seconds output rate\s+(\d+)\s+bits/sec', output)
    if output_match:
        result["output_rate_bps"] = int(output_match.group(1))

    # Errors: NX-OS uses singular "input error" / "output error"
    in_err = re.search(r'(\d+)\s+input error', output)
    if in_err:
        result["input_errors"] = int(in_err.group(1))

    out_err = re.search(r'(\d+)\s+output error', output)
    if out_err:
        result["output_errors"] = int(out_err.group(1))

    # Utilization
    if result["bandwidth_kbit"] > 0:
        bandwidth_bps = result["bandwidth_kbit"] * 1000
        total_rate = result["input_rate_bps"] + result["output_rate_bps"]
        result["utilization_percent"] = round((total_rate / bandwidth_bps) * 100, 2)

    return result
