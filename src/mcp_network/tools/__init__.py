"""
Network diagnostic MCP tools
"""

import json
from datetime import datetime, timezone
from mcp_network.app import mcp
from mcp_network.collectors import get_network
from mcp_network.graph.pathfinder import find_path, get_path_details, calculate_total_latency


# Thresholds for anomaly detection (percentage)
CPU_THRESHOLD = 80.0
INTERFACE_UTILIZATION_THRESHOLD = 80.0
INTERFACE_ERROR_THRESHOLD = 100


@mcp.tool()
async def get_path(src_device: str, dst_device: str) -> str:
    """
    Get the network path between two devices.
    
    Args:
        src_device: Source device ID (e.g., "R1")
        dst_device: Destination device ID (e.g., "R7")
    
    Returns:
        JSON string with path information including hops and total latency
    """
    try:
        network = get_network()
        
        # Find shortest path
        path = find_path(network.graph, src_device, dst_device)
        
        # Get hop details
        hops = get_path_details(network.graph, path)
        
        # Calculate total latency
        total_latency = calculate_total_latency(network.graph, path)
        
        result = {
            "src_device": src_device,
            "dst_device": dst_device,
            "path": path,
            "hops": hops,
            "total_latency_ms": round(total_latency, 2),
            "hop_count": len(path) - 1,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        return json.dumps(result, indent=2)
        
    except ValueError as e:
        error_result = {
            "error": str(e),
            "src_device": src_device,
            "dst_device": dst_device
        }
        return json.dumps(error_result, indent=2)


@mcp.tool()
async def get_device_status(device_id: str) -> str:
    """
    Get detailed status for a specific network device.
    
    Args:
        device_id: Device identifier (e.g., "R1")
    
    Returns:
        JSON string with device CPU, memory, and interface status
    """
    try:
        network = get_network()
        
        if device_id not in network.devices:
            error_result = {
                "error": f"Device '{device_id}' not found",
                "available_devices": list(network.devices.keys())
            }
            return json.dumps(error_result, indent=2)
        
        device = network.devices[device_id]
        
        # Detect anomalies
        issues = []
        if device.cpu_usage > CPU_THRESHOLD:
            issues.append({
                "type": "high_cpu",
                "metric": "cpu_usage",
                "value": device.cpu_usage,
                "threshold": CPU_THRESHOLD,
                "severity": "warning"
            })
        
        # Check interfaces
        interface_issues = []
        for interface in device.interfaces:
            if interface.utilization > INTERFACE_UTILIZATION_THRESHOLD:
                interface_issues.append({
                    "interface": interface.name,
                    "type": "high_utilization",
                    "value": interface.utilization,
                    "threshold": INTERFACE_UTILIZATION_THRESHOLD,
                    "severity": "warning"
                })
            
            if interface.errors > INTERFACE_ERROR_THRESHOLD:
                interface_issues.append({
                    "interface": interface.name,
                    "type": "high_errors",
                    "value": interface.errors,
                    "threshold": INTERFACE_ERROR_THRESHOLD,
                    "severity": "warning"
                })
        
        result = {
            "device_id": device_id,
            "device_type": device.device_type,
            "cpu_usage": round(device.cpu_usage, 1),
            "memory_usage": round(device.memory_usage, 1),
            "interfaces": [
                {
                    "name": iface.name,
                    "status": iface.status,
                    "utilization": round(iface.utilization, 1),
                    "errors": iface.errors
                }
                for iface in device.interfaces
            ],
            "issues": issues + interface_issues,
            "health_status": "degraded" if (issues or interface_issues) else "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        return json.dumps(result, indent=2)
        
    except Exception as e:
        error_result = {"error": str(e)}
        return json.dumps(error_result, indent=2)


@mcp.tool()
async def diagnose_latency(src_device: str, dst_device: str) -> str:
    """
    Diagnose latency issues between two devices w/ root cause analysis.
    
    Finds network path, collects metrics for each hop, detects
    anomalies, & provides troubleshooting recs.

    Args:
        src_device: Source device ID
        dst_device: Destination device ID 
    
    Returns:
        JSON string with path, findings, root cause analysis, and summary
    """
    try:
        network = get_network()
        
        # Find path
        path = find_path(network.graph, src_device, dst_device)
        hops = get_path_details(network.graph, path)
        total_latency = calculate_total_latency(network.graph, path)
        
        # Collect metrics & detect anomalies for each device in path
        findings = []
        
        for device_id in path:
            device = network.devices[device_id]
            
            # check CPU
            if device.cpu_usage > CPU_THRESHOLD:
                findings.append({
                    "device": device_id,
                    "type": "high_cpu",
                    "metric": "cpu_usage",
                    "value": round(device.cpu_usage, 1),
                    "threshold": CPU_THRESHOLD,
                    "severity": "warning",
                    "impact": "May cause packet processing delays"
                })
            
            # check interfaces - only those in the path
            for hop in hops:
                if hop["from_device"] == device_id:
                    interface_name = hop["from_interface"]
                    # Find this interface
                    interface = next((i for i in device.interfaces if i.name == interface_name), None)
                    
                    if interface:
                        if interface.utilization > INTERFACE_UTILIZATION_THRESHOLD:
                            findings.append({
                                "device": device_id,
                                "interface": interface.name,
                                "type": "high_utilization",
                                "metric": "interface_utilization",
                                "value": round(interface.utilization, 1),
                                "threshold": INTERFACE_UTILIZATION_THRESHOLD,
                                "severity": "warning",
                                "impact": "Link congestion causing queuing delays"
                            })
                        
                        if interface.errors > INTERFACE_ERROR_THRESHOLD:
                            findings.append({
                                "device": device_id,
                                "interface": interface.name,
                                "type": "high_errors",
                                "metric": "interface_errors",
                                "value": interface.errors,
                                "threshold": INTERFACE_ERROR_THRESHOLD,
                                "severity": "warning",
                                "impact": "Packet retransmissions increasing latency"
                            })
        
        #  summarize
        if findings:
            primary_issue = findings[0]  # usually most critical (first)
            summary = f"Latency issue detected: {primary_issue['type']} on {primary_issue['device']}"
            if 'interface' in primary_issue:
                summary += f" interface {primary_issue['interface']}"
            summary += f" ({primary_issue['value']}{'' if primary_issue['type'] == 'high_errors' else '%'} exceeds threshold of {primary_issue['threshold']})"
        else:
            summary = "No anomalies detected. Path appears healthy."
        
        # Build result
        result = {
            "src_device": src_device,
            "dst_device": dst_device,
            "path": path,
            "hops": hops,
            "total_latency_ms": round(total_latency, 2),
            "findings": findings,
            "summary": summary,
            "health_status": "issue_detected" if findings else "healthy",
            "recommendation": _generate_recommendation(findings),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        return json.dumps(result, indent=2)
        
    except ValueError as e:
        error_result = {
            "error": str(e),
            "src_device": src_device,
            "dst_device": dst_device
        }
        return json.dumps(error_result, indent=2)


def _generate_recommendation(findings: list[dict]) -> str:
    """Generate recs based on findings."""
    if not findings:
        return "No action needed. Network path is operating normally."
    
    recommendations = []
    
    for finding in findings:
        if finding["type"] == "high_cpu":
            recommendations.append(f"Investigate high CPU on {finding['device']} - check running processes and traffic load")
        elif finding["type"] == "high_utilization":
            recommendations.append(f"Consider upgrading bandwidth on {finding['device']} {finding['interface']} or rerouting traffic")
        elif finding["type"] == "high_errors":
            recommendations.append(f"Check physical layer on {finding['device']} {finding['interface']} - inspect cables and optics")
    
    return " | ".join(recommendations[:3])  # Top 3 recommendations
