"""
Parsers for Cisco IOS-XE CLI output (IOSv, CSR1000v, Cat8000v).
"""

import re
from typing import Dict, List


def parse_memory_summary(output: str) -> Dict[str, float]:
    """
    Parse 'show processes memory sorted' or 'show memory statistics' output.
    
    Returns:
        Dict with 'total_mb', 'used_mb', 'free_mb', 'usage_percent'
    """
    result = {
        "total_mb": 0.0,
        "used_mb": 0.0,
        "free_mb": 0.0,
        "usage_percent": 0.0,
    }
    
    # Try parsing "Processor Pool" line from 'show processes memory sorted'
    # Example: "Processor Pool Total:  412852636 Used:  103498492 Free:  309354144"
    pool_match = re.search(
        r'Processor\s+Pool\s+Total:\s+(\d+)\s+Used:\s+(\d+)\s+Free:\s+(\d+)',
        output,
        re.IGNORECASE
    )
    
    if pool_match:
        total_bytes = int(pool_match.group(1))
        used_bytes = int(pool_match.group(2))
        free_bytes = int(pool_match.group(3))
        
        result["total_mb"] = total_bytes / (1024 * 1024)
        result["used_mb"] = used_bytes / (1024 * 1024)
        result["free_mb"] = free_bytes / (1024 * 1024)
        if total_bytes > 0:
            result["usage_percent"] = (used_bytes / total_bytes) * 100
        return result
    
    # Alternative: parse 'show memory statistics'
    # Example: "Processor   3E6413E0   412852636   103498492   309354144"
    mem_match = re.search(
        r'Processor\s+\S+\s+(\d+)\s+(\d+)\s+(\d+)',
        output
    )
    
    if mem_match:
        total_bytes = int(mem_match.group(1))
        used_bytes = int(mem_match.group(2))
        free_bytes = int(mem_match.group(3))
        
        result["total_mb"] = total_bytes / (1024 * 1024)
        result["used_mb"] = used_bytes / (1024 * 1024)
        result["free_mb"] = free_bytes / (1024 * 1024)
        if total_bytes > 0:
            result["usage_percent"] = (used_bytes / total_bytes) * 100
        return result
    
    return result


def parse_cpu_usage(output: str) -> float:
    """
    Parse 'show processes cpu' output.
    
    Example line:
    "CPU utilization for five seconds: 5%/0%; one minute: 6%; five minutes: 5%"
    
    Returns:
        CPU usage percentage (5-minute average)
    """
    # Match the CPU utilization line
    match = re.search(
        r'CPU utilization.*five minutes:\s*(\d+)%',
        output,
        re.IGNORECASE
    )
    
    if match:
        return float(match.group(1))
    
    # Alternative format
    match = re.search(r'five minutes:\s*(\d+)%', output)
    if match:
        return float(match.group(1))
    
    return 0.0


def parse_interface_brief(output: str) -> List[Dict[str, str]]:
    """
    Parse 'show ip interface brief' output.
    
    Example:
    Interface              IP-Address      OK? Method Status                Protocol
    GigabitEthernet0/0     10.1.1.1        YES NVRAM  up                    up
    GigabitEthernet0/1     unassigned      YES NVRAM  administratively down down
    
    Returns:
        List of dicts with 'name', 'ip_address', 'status', 'protocol'
    """
    interfaces = []
    
    lines = output.strip().split('\n')
    
    for line in lines:
        # Skip header and empty lines
        if not line.strip():
            continue
        if 'Interface' in line and 'IP-Address' in line:
            continue
        if line.startswith('---'):
            continue
            
        # Parse interface line
        # Format: Interface IP-Address OK? Method Status Protocol
        parts = line.split()
        
        if len(parts) >= 6:
            interface_name = parts[0]
            ip_address = parts[1]
            # Status might be "administratively down" (2 words) or "up" (1 word)
            # Protocol is always the last field
            protocol = parts[-1].lower()
            
            # Find status - it's before protocol
            if 'administratively' in line.lower():
                status = 'admin_down'
            else:
                status = parts[-2].lower()
            
            interfaces.append({
                "name": interface_name,
                "ip_address": ip_address,
                "status": status,
                "protocol": protocol,
            })
    
    return interfaces


def parse_interface_detail(output: str) -> Dict[str, any]:
    """
    Parse 'show interfaces <name>' output for detailed stats.
    
    Returns:
        Dict with 'bandwidth_kbps', 'input_rate_bps', 'output_rate_bps',
        'input_errors', 'output_errors', 'utilization_percent'
    """
    result = {
        "bandwidth_kbps": 0,
        "input_rate_bps": 0,
        "output_rate_bps": 0,
        "input_errors": 0,
        "output_errors": 0,
        "utilization_percent": 0.0,
    }
    
    # Parse bandwidth: "BW 1000000 Kbit"
    bw_match = re.search(r'BW\s+(\d+)\s+Kbit', output)
    if bw_match:
        result["bandwidth_kbps"] = int(bw_match.group(1))
    
    # Parse input rate: "5 minute input rate 1000 bits/sec"
    input_match = re.search(r'5 minute input rate\s+(\d+)\s+bits/sec', output)
    if input_match:
        result["input_rate_bps"] = int(input_match.group(1))
    
    # Parse output rate: "5 minute output rate 1000 bits/sec"
    output_match = re.search(r'5 minute output rate\s+(\d+)\s+bits/sec', output)
    if output_match:
        result["output_rate_bps"] = int(output_match.group(1))
    
    # Parse input errors: "0 input errors"
    in_err_match = re.search(r'(\d+)\s+input errors', output)
    if in_err_match:
        result["input_errors"] = int(in_err_match.group(1))
    
    # Parse output errors: "0 output errors"
    out_err_match = re.search(r'(\d+)\s+output errors', output)
    if out_err_match:
        result["output_errors"] = int(out_err_match.group(1))
    
    # Calculate utilization
    if result["bandwidth_kbps"] > 0:
        bandwidth_bps = result["bandwidth_kbps"] * 1000
        total_rate = result["input_rate_bps"] + result["output_rate_bps"]
        result["utilization_percent"] = (total_rate / bandwidth_bps) * 100
    
    return result
