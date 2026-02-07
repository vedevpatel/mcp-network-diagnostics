"""
Network diagnostic MCP tools
"""

import json
from datetime import datetime, timezone
from mcp_network.app import mcp
from mcp_network.collectors import get_network
from mcp_network.graph.pathfinder import find_path, get_path_details, calculate_total_latency, find_alternate_paths
from mcp_network.trends.store import MetricStore
from mcp_network.trends.analyzer import analyze_trend
from mcp_network.trends.anomaly import detect_all_anomalies


# Default thresholds — overridden by "thresholds:" block in topology YAML
_DEFAULTS = {
    "cpu": 80.0,
    "utilization": 80.0,
    "errors": 100,
}

_ANOMALY_DEFAULTS = {
    "z_score_threshold": 2.0,
    "rate_shift_threshold": 3.0,
    "volatility_ratio_threshold": 3.0,
    "min_samples": 5,
}

# Module-level metric history — persists across tool calls within a session
_metric_store = MetricStore()


def _get_thresholds() -> dict:
    """Read thresholds from the active collector, fall back to defaults."""
    network = get_network()
    t = getattr(network, "thresholds", {})
    return {
        "cpu": float(t.get("cpu", _DEFAULTS["cpu"])),
        "utilization": float(t.get("utilization", _DEFAULTS["utilization"])),
        "errors": int(t.get("errors", _DEFAULTS["errors"])),
    }


def _snapshot_metrics() -> None:
    """Record current metrics into the trend store.

    Calls refresh() on the collector first if available (simulated).
    """
    network = get_network()
    if hasattr(network, "refresh"):
        network.refresh()
    _metric_store.record_all(network.devices)


def _get_anomaly_config() -> dict:
    """Read anomaly detection config, fall back to defaults."""
    network = get_network()
    t = getattr(network, "thresholds", {})
    ac = t.get("anomaly", {}) if isinstance(t, dict) else {}
    return {k: ac.get(k, v) for k, v in _ANOMALY_DEFAULTS.items()}


def _get_anomaly_flags(device_id: str, anomaly_config: dict) -> list[dict]:
    """Run anomaly detection on all tracked metrics for a device."""
    flags = []
    for metric, series in _metric_store.get_device_metrics(device_id).items():
        anomalies = detect_all_anomalies(
            series, metric,
            z_score_threshold=anomaly_config["z_score_threshold"],
            rate_shift_threshold=anomaly_config["rate_shift_threshold"],
            volatility_ratio_threshold=anomaly_config["volatility_ratio_threshold"],
            min_samples=anomaly_config["min_samples"],
        )
        for a in anomalies:
            flags.append({
                "metric": a.metric_name,
                "type": a.anomaly_type,
                "current_value": round(a.current_value, 2),
                "baseline_mean": round(a.baseline_mean, 2),
                "baseline_stddev": round(a.baseline_stddev, 2),
                "score": round(a.score, 2),
                "severity": a.severity,
                "confidence": a.confidence,
                "description": a.description,
            })
    return flags


def _get_trend_indicators(device_id: str, thresholds: dict) -> list[dict]:
    """Build trend indicator dicts for all tracked metrics on a device."""
    indicators = []
    for metric, series in _metric_store.get_device_metrics(device_id).items():
        # Pick the right threshold
        if metric == "cpu":
            thresh = thresholds["cpu"]
        elif metric == "memory":
            thresh = thresholds["cpu"]  # no separate memory threshold; use cpu
        elif metric.endswith(":util"):
            thresh = thresholds["utilization"]
        elif metric.endswith(":errors"):
            thresh = float(thresholds["errors"])
        else:
            continue

        result = analyze_trend(series, metric, thresh)
        if result is None:
            continue
        indicators.append({
            "metric": metric,
            "direction": result.direction,
            "rate_per_minute": result.rate_per_minute,
            "time_to_threshold_minutes": result.time_to_threshold_minutes,
            "confidence": result.confidence,
        })
    return indicators


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
        
        # Snapshot for trend tracking
        _snapshot_metrics()
        trends = _get_trend_indicators(device_id, thresholds)
        anomaly_flags = _get_anomaly_flags(device_id, _get_anomaly_config())

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
            "trends": trends,
            "anomalies": anomaly_flags,
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
        
        # Alternate-path suggestion — only when there's something to avoid
        alternate = None
        if findings:
            bottleneck_devices = {f["device"] for f in findings}
            candidates = find_alternate_paths(network.graph, path, bottleneck_devices)
            if candidates:
                best = candidates[0]
                alternate = {
                    "path": best["path"],
                    "total_latency_ms": best["total_latency_ms"],
                    "avoids_devices": best["avoids"],
                    "avoids_all_bottlenecks": best["avoids_all"],
                }

        # Trend warnings for devices on the path
        _snapshot_metrics()
        trend_warnings = []
        for device_id in path:
            for indicator in _get_trend_indicators(device_id, thresholds):
                if indicator["direction"] == "rising" and indicator["time_to_threshold_minutes"] is not None:
                    trend_warnings.append({
                        "device": device_id,
                        **indicator,
                    })

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
            "recommendation": _generate_recommendation(findings, alternate),
            "alternate_path": alternate,
            "trend_warnings": trend_warnings,
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


def _generate_recommendation(findings: list[dict], alternate: dict | None = None) -> str:
    """Generate recs based on findings and, when available, an alternate path."""
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

    if alternate:
        via = " → ".join(alternate["path"])
        if alternate["avoids_all_bottlenecks"]:
            recommendations.append(f"Alternate path avoids all bottlenecks: {via} ({alternate['total_latency_ms']} ms)")
        else:
            avoids_str = ", ".join(alternate["avoids_devices"])
            recommendations.append(f"Alternate path avoids {avoids_str}: {via} ({alternate['total_latency_ms']} ms)")

    return " | ".join(recommendations[:3])


@mcp.tool()
async def predict_path_health(
    src_device: str,
    dst_device: str,
    horizon_minutes: int = 5,
) -> str:
    """
    Predict future path health using metric trend analysis.

    Combines current path diagnosis with trend-based predictions
    to warn about metrics approaching thresholds.

    Args:
        src_device: Source device ID (e.g., "R1")
        dst_device: Destination device ID (e.g., "R10")
        horizon_minutes: How far ahead to predict (default: 5 minutes)

    Returns:
        JSON with current diagnosis, predictions per hop, and risk assessment
    """
    try:
        network = get_network()
        thresholds = _get_thresholds()

        # Record a fresh snapshot
        _snapshot_metrics()

        # Find path
        path = find_path(network.graph, src_device, dst_device)
        hops = get_path_details(network.graph, path)
        total_latency = calculate_total_latency(network.graph, path)

        # Current threshold checks (same logic as diagnose_latency)
        findings = []
        for device_id in path:
            device = network.devices[device_id]
            if device.cpu_usage > thresholds["cpu"]:
                findings.append({
                    "device": device_id,
                    "type": "high_cpu",
                    "metric": "cpu_usage",
                    "value": round(device.cpu_usage, 1),
                    "threshold": thresholds["cpu"],
                })
            for hop in hops:
                if hop["from_device"] == device_id:
                    intf_names = [hop["from_interface"]]
                elif hop["to_device"] == device_id:
                    intf_names = [hop["to_interface"]]
                else:
                    continue
                for interface_name in intf_names:
                    interface = next(
                        (i for i in device.interfaces if i.name == interface_name), None
                    )
                    if not interface:
                        continue
                    if interface.utilization > thresholds["utilization"]:
                        findings.append({
                            "device": device_id,
                            "interface": interface.name,
                            "type": "high_utilization",
                            "value": round(interface.utilization, 1),
                            "threshold": thresholds["utilization"],
                        })
                    if interface.errors > thresholds["errors"]:
                        findings.append({
                            "device": device_id,
                            "interface": interface.name,
                            "type": "high_errors",
                            "value": interface.errors,
                            "threshold": thresholds["errors"],
                        })

        # Trend predictions for each device on path
        predictions = []
        has_breach_in_horizon = False
        has_rising = False

        for device_id in path:
            device = network.devices[device_id]
            # Metrics to analyze: cpu, memory, plus relevant interfaces
            metrics_to_check = [
                ("cpu", device.cpu_usage, thresholds["cpu"]),
                ("memory", device.memory_usage, thresholds["cpu"]),
            ]
            for hop in hops:
                if hop["from_device"] == device_id:
                    iname = hop["from_interface"]
                elif hop["to_device"] == device_id:
                    iname = hop["to_interface"]
                else:
                    continue
                iface = next((i for i in device.interfaces if i.name == iname), None)
                if iface:
                    metrics_to_check.append(
                        (f"interface:{iname}:util", iface.utilization, thresholds["utilization"])
                    )

            for metric_key, current_val, thresh in metrics_to_check:
                series = _metric_store.get_series(device_id, metric_key)
                if series is None:
                    continue
                trend = analyze_trend(series, metric_key, thresh, float(horizon_minutes))
                if trend is None:
                    continue
                if trend.direction == "rising" and trend.time_to_threshold_minutes is not None:
                    has_rising = True
                    warning = f"{metric_key} predicted to breach {thresh} in {trend.time_to_threshold_minutes} min"
                    if trend.will_breach:
                        has_breach_in_horizon = True
                    if current_val >= thresh:
                        warning = f"{metric_key} already above threshold and rising"
                    predictions.append({
                        "device": device_id,
                        "metric": metric_key,
                        "current_value": round(trend.current_value, 1),
                        "rate_per_minute": trend.rate_per_minute,
                        "direction": trend.direction,
                        "time_to_threshold_minutes": trend.time_to_threshold_minutes,
                        "will_breach": trend.will_breach,
                        "confidence": trend.confidence,
                        "warning": warning,
                    })

        # Overall risk
        if has_breach_in_horizon:
            overall_risk = "high"
        elif has_rising:
            overall_risk = "medium"
        else:
            overall_risk = "low"

        # Summary
        if findings:
            current_summary = f"{len(findings)} current issue(s) detected"
        else:
            current_summary = "Path currently healthy"

        if predictions:
            pred_summary = f"{len(predictions)} metric(s) trending toward threshold"
        else:
            pred_summary = "No concerning trends"

        # Recommendation
        breach_preds = [p for p in predictions if p["will_breach"]]
        if breach_preds:
            first = breach_preds[0]
            recommendation = (
                f"{first['device']} {first['metric']} trending toward threshold "
                f"— consider rerouting before breach"
            )
        elif findings:
            recommendation = _generate_recommendation(findings)
        else:
            recommendation = "No action needed. Path is healthy with stable trends."

        result = {
            "src_device": src_device,
            "dst_device": dst_device,
            "path": path,
            "hops": hops,
            "total_latency_ms": round(total_latency, 2),
            "horizon_minutes": horizon_minutes,
            "current_diagnosis": {
                "findings": findings,
                "summary": current_summary,
                "health_status": "issue_detected" if findings else "healthy",
            },
            "predictions": predictions,
            "prediction_summary": pred_summary,
            "overall_risk": overall_risk,
            "recommendation": recommendation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return json.dumps(result, indent=2)

    except ValueError as e:
        return json.dumps({
            "error": str(e),
            "src_device": src_device,
            "dst_device": dst_device,
        }, indent=2)


@mcp.tool()
async def detect_anomalies() -> str:
    """
    Detect unusual metric behavior across the network.

    Compares current values against rolling statistical baselines
    using z-score, rate-shift, and volatility detection.

    Returns devices and metrics that are behaving anomalously,
    even if they haven't breached any threshold.
    """
    _snapshot_metrics()
    anomaly_config = _get_anomaly_config()

    all_anomalies = []
    device_anomaly_counts: dict[str, list[str]] = {}

    network = get_network()
    for device_id in network.devices:
        flags = _get_anomaly_flags(device_id, anomaly_config)
        for f in flags:
            f["device_id"] = device_id
            all_anomalies.append(f)
        if flags:
            device_anomaly_counts[device_id] = [f["metric"] for f in flags]

    # Multi-metric correlation
    correlated = []
    for device_id, metrics in device_anomaly_counts.items():
        if len(metrics) >= 2:
            correlated.append({
                "device_id": device_id,
                "anomaly_count": len(metrics),
                "metrics": metrics,
                "note": "Multiple metrics anomalous simultaneously -- possible systemic issue",
            })

    # Check sample coverage
    has_enough = any(
        series.count >= anomaly_config["min_samples"]
        for series in (
            _metric_store.get_series(did, m)
            for did in network.devices
            for m in _metric_store.get_device_metrics(did)
        )
        if series is not None
    )
    sample_coverage = "sufficient" if has_enough else "building"

    # Summary
    if all_anomalies:
        device_set = {a["device_id"] for a in all_anomalies}
        summary = f"{len(all_anomalies)} anomaly(ies) detected across {len(device_set)} device(s)."
        if correlated:
            summary += (
                f" {correlated[0]['device_id']} has correlated anomalies"
                f" on {correlated[0]['anomaly_count']} metrics."
            )
    else:
        summary = "No anomalies detected. All metrics within normal statistical baselines."

    result = {
        "anomalies": all_anomalies,
        "correlated_devices": correlated,
        "summary": summary,
        "sample_coverage": sample_coverage,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(result, indent=2)


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
