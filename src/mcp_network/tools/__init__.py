"""
Network diagnostic MCP tools
"""

import json
from datetime import datetime, timezone
from mcp_network.app import mcp
from mcp_network.collectors import get_network
from mcp_network.graph.pathfinder import find_path, get_path_details, calculate_total_latency


# Default thresholds — overridden by "thresholds:" block in topology YAML
_DEFAULTS = {
    "cpu": 80.0,
    "utilization": 80.0,
    "errors": 100,
}


def _get_thresholds() -> dict:
    """Read thresholds from the active collector, fall back to defaults."""
    network = get_network()
    t = getattr(network, "thresholds", {})
    return {
        "cpu": float(t.get("cpu", _DEFAULTS["cpu"])),
        "utilization": float(t.get("utilization", _DEFAULTS["utilization"])),
        "errors": int(t.get("errors", _DEFAULTS["errors"])),
    }


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
        thresholds = _get_thresholds()

        # Detect anomalies
        issues = []
        if device.cpu_usage > thresholds["cpu"]:
            issues.append({
                "type": "high_cpu",
                "metric": "cpu_usage",
                "value": device.cpu_usage,
                "threshold": thresholds["cpu"],
                "severity": "warning"
            })

        # Check interfaces
        interface_issues = []
        for interface in device.interfaces:
            if interface.utilization > thresholds["utilization"]:
                interface_issues.append({
                    "interface": interface.name,
                    "type": "high_utilization",
                    "value": interface.utilization,
                    "threshold": thresholds["utilization"],
                    "severity": "warning"
                })

            if interface.errors > thresholds["errors"]:
                interface_issues.append({
                    "interface": interface.name,
                    "type": "high_errors",
                    "value": interface.errors,
                    "threshold": thresholds["errors"],
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
async def list_devices() -> str:
    """
    List all devices in the network topology.

    Returns device IDs, types, and health status at a glance.
    Also indicates which device is the local device (used by
    diagnose_from_here as the default source).

    Use this first if you don't know what devices are available.
    """
    network = get_network()
    local = getattr(network, "local_device", None)
    thresholds = _get_thresholds()

    devices = []
    for device_id, device in network.devices.items():
        has_issues = device.cpu_usage > thresholds["cpu"] or any(
            i.utilization > thresholds["utilization"] or i.errors > thresholds["errors"]
            for i in device.interfaces
        )
        devices.append({
            "device_id": device_id,
            "type": device.device_type,
            "local": device_id == local,
            "health_status": "degraded" if has_issues else "healthy",
            "cpu_usage": round(device.cpu_usage, 1),
            "memory_usage": round(device.memory_usage, 1),
        })

    result = {
        "local_device": local,
        "devices": devices,
        "hint": f"To diagnose latency from {local}, call diagnose_from_here with just a dst_device." if local else "No local_device set. Use diagnose_latency with both src and dst.",
    }
    return json.dumps(result, indent=2)


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
        thresholds = _get_thresholds()

        # Find path
        path = find_path(network.graph, src_device, dst_device)
        hops = get_path_details(network.graph, path)
        total_latency = calculate_total_latency(network.graph, path)

        # Collect metrics & detect anomalies for each device in path
        findings = []

        for device_id in path:
            device = network.devices[device_id]

            # check CPU
            if device.cpu_usage > thresholds["cpu"]:
                findings.append({
                    "device": device_id,
                    "type": "high_cpu",
                    "metric": "cpu_usage",
                    "value": round(device.cpu_usage, 1),
                    "threshold": thresholds["cpu"],
                    "severity": "warning",
                    "impact": "May cause packet processing delays"
                })

            # check interfaces - both egress (from) and ingress (to) on each hop
            for hop in hops:
                if hop["from_device"] == device_id:
                    intf_names = [hop["from_interface"]]
                elif hop["to_device"] == device_id:
                    intf_names = [hop["to_interface"]]
                else:
                    continue

                for interface_name in intf_names:
                    interface = next((i for i in device.interfaces if i.name == interface_name), None)
                    if not interface:
                        continue

                    if interface.utilization > thresholds["utilization"]:
                        findings.append({
                            "device": device_id,
                            "interface": interface.name,
                            "hop": hop["hop_number"],
                            "type": "high_utilization",
                            "metric": "interface_utilization",
                            "value": round(interface.utilization, 1),
                            "threshold": thresholds["utilization"],
                            "severity": "warning",
                            "impact": "Link congestion causing queuing delays"
                        })

                    if interface.errors > thresholds["errors"]:
                        findings.append({
                            "device": device_id,
                            "interface": interface.name,
                            "hop": hop["hop_number"],
                            "type": "high_errors",
                            "metric": "interface_errors",
                            "value": interface.errors,
                            "threshold": thresholds["errors"],
                            "severity": "warning",
                            "impact": "Packet retransmissions increasing latency"
                        })
        
        #  summarize — pick the worst finding, not the first
        if findings:
            type_priority = {"high_errors": 0, "high_utilization": 1, "high_cpu": 2}
            primary_issue = min(findings, key=lambda f: (type_priority.get(f["type"], 99), -f["value"]))

            hop_count = len(hops)
            if "hop" in primary_issue:
                hop_label = f"hop {primary_issue['hop']} of {hop_count}, "
                hop_context = hops[primary_issue["hop"] - 1]
                hop_label += f"{hop_context['from_device']} → {hop_context['to_device']} — "
            else:
                hop_label = ""

            unit = "" if primary_issue["type"] == "high_errors" else "%"
            summary = (
                f"Bottleneck at {hop_label}{primary_issue['device']}"
                f" {primary_issue.get('interface', 'CPU')}: "
                f"{primary_issue['type'].replace('_', ' ')} "
                f"({primary_issue['value']}{unit})"
            )
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


@mcp.tool()
async def diagnose_from_here(dst_device: str) -> str:
    """
    Diagnose latency from the local device to a destination.

    Uses the local_device defined in the topology as the source.
    This is the single-argument entry point: the engineer specifies
    only where traffic is going, and the tool figures out the path
    and where the bottleneck is.

    Args:
        dst_device: Destination device ID (e.g., "R10", "devnet-iosxe-1")

    Returns:
        JSON string with path, findings, root cause analysis, and summary
    """
    network = get_network()

    if not getattr(network, "local_device", None):
        return json.dumps({
            "error": "No local_device configured. Add 'local_device: <device_id>' to your topology file, or use diagnose_latency with an explicit source.",
            "available_devices": list(network.devices.keys())
        }, indent=2)

    return await diagnose_latency(src_device=network.local_device, dst_device=dst_device)


@mcp.tool()
async def run_command(device_id: str, command: str) -> str:
    """
    Run a show command on a device and return the raw output.

    Only 'show' commands are allowed — this server is read-only.
    Useful for ad-hoc investigation after diagnose_latency flags
    something: e.g. "show processes cpu sorted", "show queues",
    "show ip route".

    Only works with the ssh collector. Returns an error on
    simulated or prometheus collectors.

    Args:
        device_id: Target device ID (use list_devices to find them)
        command: A 'show' command to run (e.g. "show version")

    Returns:
        Raw command output as a string, or a JSON error.
    """
    if not command.strip().lower().startswith("show"):
        return json.dumps({
            "error": "Only 'show' commands are permitted. This server is read-only.",
            "command": command,
        }, indent=2)

    network = get_network()

    if not hasattr(network, "run_command"):
        return json.dumps({
            "error": "run_command requires the ssh collector. Current collector does not support live command execution.",
            "hint": "Start the server with --collector ssh and a topology file.",
        }, indent=2)

    try:
        output = network.run_command(device_id, command.strip())
        return json.dumps({
            "device_id": device_id,
            "command": command.strip(),
            "output": output,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, indent=2)
    except ValueError as e:
        return json.dumps({"error": str(e), "device_id": device_id}, indent=2)
