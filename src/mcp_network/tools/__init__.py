"""
Network diagnostic MCP tools
"""

import asyncio
import json
import time
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


# ============================================================================
# P2a: Collection Health Tools
# ============================================================================

@mcp.tool()
async def get_collection_health() -> str:
    """
    Get data collection health status for all devices.

    Shows per-device reachability, data staleness, failure rates, and
    overall collection quality score. Use this to understand data quality
    before trusting diagnostic results.

    Returns:
        JSON object with:
        - collection_quality_score: 0.0 to 1.0 (1.0 = perfect)
        - reachability_percentage: % of devices currently reachable
        - device_health: Per-device health details
        - stale_devices: List of devices with stale data
        - unreachable_devices: List of unreachable devices
        - summary: Human-readable summary
    """
    from mcp_network.collectors.health import get_health_tracker

    health_tracker = get_health_tracker()
    health_summary = health_tracker.get_health_summary()

    # Build device health details
    device_details = {}
    for device_id, health in health_summary.device_health.items():
        device_details[device_id] = {
            "reachable": health.reachable,
            "staleness": health.staleness_level,
            "data_age_seconds": round(health.data_age_seconds, 1),
            "failure_rate": round(health.failure_rate * 100, 1),
            "consecutive_failures": health.consecutive_failures,
            "last_error": health.last_error,
        }

    stale_devices = [
        device_id for device_id, health in health_summary.device_health.items()
        if health.is_stale
    ]

    unreachable_devices = [
        device_id for device_id, health in health_summary.device_health.items()
        if not health.reachable
    ]

    return json.dumps({
        "collection_quality_score": round(health_summary.collection_quality_score, 3),
        "reachability_percentage": round(health_summary.reachability_percentage, 1),
        "total_devices": health_summary.total_devices,
        "reachable_devices": health_summary.reachable_devices,
        "unreachable_devices_count": health_summary.unreachable_devices,
        "stale_devices_count": health_summary.stale_devices,
        "device_health": device_details,
        "stale_devices": stale_devices,
        "unreachable_devices": unreachable_devices,
        "summary": health_summary.summary(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, indent=2)


# ============================================================================
# P2b: Config Change Correlation Tools
# ============================================================================

@mcp.tool()
async def collect_device_configs() -> str:
    """
    Collect configuration snapshots from all devices.

    Triggers on-demand config collection via SSH for tracking changes.
    Automatically detects and logs any config changes since last collection.

    Only works with SSH collector. Returns collection summary.

    Returns:
        JSON object with:
        - successful: Number of devices successfully collected
        - failed: Number of devices that failed collection
        - changes_detected: List of devices with detected changes
        - timestamp: Collection timestamp
    """
    network = get_network()

    if not hasattr(network, "collect_configs"):
        return json.dumps({
            "error": "collect_device_configs requires the ssh collector. Current collector does not support config collection.",
            "hint": "Start the server with --collector ssh",
        }, indent=2)

    from mcp_network.config import get_config_tracker

    config_tracker = get_config_tracker()

    # Track pre-collection state
    pre_hashes = {}
    for device_id in network.devices:
        snapshot = config_tracker.get_latest_snapshot(device_id)
        if snapshot:
            pre_hashes[device_id] = snapshot.config_hash

    # Collect configs
    try:
        network.collect_configs()
    except Exception as e:
        return json.dumps({
            "error": f"Config collection failed: {e}",
        }, indent=2)

    # Detect changes
    changes_detected = []
    successful = 0
    failed = 0

    for device_id in network.devices:
        snapshot = config_tracker.get_latest_snapshot(device_id)
        if snapshot:
            successful += 1
            old_hash = pre_hashes.get(device_id)
            if old_hash and old_hash != snapshot.config_hash:
                changes_detected.append(device_id)
        else:
            failed += 1

    return json.dumps({
        "successful": successful,
        "failed": failed,
        "changes_detected": changes_detected,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, indent=2)


@mcp.tool()
async def get_config_history(device_id: str, limit: int = 10) -> str:
    """
    Get configuration change history for a device.

    Shows recent config changes with timestamps and hashes. Use this to
    correlate anomalies with configuration changes.

    Args:
        device_id: Target device ID
        limit: Maximum number of changes to return (default 10)

    Returns:
        JSON object with:
        - device_id: Target device
        - changes: List of config changes with timestamps
        - latest_config_hash: Current config hash
        - change_count: Total changes tracked
    """
    from mcp_network.config import get_config_tracker

    config_tracker = get_config_tracker()
    changes = config_tracker.get_change_history(device_id, limit=limit)
    latest_snapshot = config_tracker.get_latest_snapshot(device_id)

    change_list = []
    for change in changes:
        change_list.append({
            "timestamp": datetime.fromtimestamp(change.change_time, timezone.utc).isoformat(),
            "age_seconds": round(change.age_seconds, 1),
            "old_hash": change.old_hash,
            "new_hash": change.new_hash,
            "description": change.description,
        })

    return json.dumps({
        "device_id": device_id,
        "changes": change_list,
        "latest_config_hash": latest_snapshot.config_hash if latest_snapshot else None,
        "change_count": len(changes),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, indent=2)


@mcp.tool()
async def compare_configs(device_id: str, time_a: str, time_b: str) -> str:
    """
    Compare device configurations at two points in time.

    Generates a unified diff showing what changed between two config snapshots.
    Useful for root cause analysis when anomalies correlate with config changes.

    Args:
        device_id: Target device ID
        time_a: Earlier timestamp (ISO format or seconds since epoch)
        time_b: Later timestamp (ISO format or seconds since epoch)

    Returns:
        JSON object with:
        - device_id: Target device
        - time_a, time_b: Resolved timestamps
        - diff: Unified diff output (lines starting with + or -)
        - changed: Boolean indicating if configs differ
    """
    from mcp_network.config import get_config_tracker

    config_tracker = get_config_tracker()

    # Parse timestamps
    try:
        if time_a.replace(".", "").isdigit():
            timestamp_a = float(time_a)
        else:
            timestamp_a = datetime.fromisoformat(time_a.replace("Z", "+00:00")).timestamp()

        if time_b.replace(".", "").isdigit():
            timestamp_b = float(time_b)
        else:
            timestamp_b = datetime.fromisoformat(time_b.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError) as e:
        return json.dumps({
            "error": f"Invalid timestamp format: {e}",
            "hint": "Use ISO format (2024-01-01T12:00:00Z) or Unix timestamp",
        }, indent=2)

    diff = config_tracker.diff_configs(device_id, timestamp_a, timestamp_b)

    if diff is None:
        return json.dumps({
            "error": "Config snapshots not found for specified times",
            "device_id": device_id,
            "time_a": time_a,
            "time_b": time_b,
        }, indent=2)

    return json.dumps({
        "device_id": device_id,
        "time_a": datetime.fromtimestamp(timestamp_a, timezone.utc).isoformat(),
        "time_b": datetime.fromtimestamp(timestamp_b, timezone.utc).isoformat(),
        "diff": diff,
        "changed": diff != "No changes detected",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, indent=2)


@mcp.tool()
async def check_config_correlation(device_id: str, window_seconds: float = 1800.0) -> str:
    """
    Check if device had config changes recently that might correlate with anomalies.

    Looks for config changes within the specified time window. Use this during
    incident investigation to quickly check if a config change preceded the issue.

    Args:
        device_id: Target device ID
        window_seconds: Time window to check (default 1800 = 30 minutes)

    Returns:
        JSON object with:
        - device_id: Target device
        - had_recent_change: Boolean
        - changes: List of recent changes
        - window_seconds: Search window used
    """
    from mcp_network.config import get_config_tracker

    config_tracker = get_config_tracker()
    changes = config_tracker.get_changes_in_window(device_id, window_seconds)

    change_list = []
    for change in changes:
        change_list.append({
            "timestamp": datetime.fromtimestamp(change.change_time, timezone.utc).isoformat(),
            "age_seconds": round(change.age_seconds, 1),
            "description": change.description,
        })

    return json.dumps({
        "device_id": device_id,
        "had_recent_change": len(changes) > 0,
        "changes": change_list,
        "window_seconds": window_seconds,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, indent=2)


# ============================================================================
# P2c: Causal Root Cause Analysis Tools
# ============================================================================

@mcp.tool()
async def explain_incident(context: str = "all") -> str:
    """
    Perform causal root cause analysis on recent anomalies.

    Analyzes temporal and topological relationships between anomalies to
    identify the most likely root cause(s). Uses causal graph analysis to
    determine which device/metric triggered cascading failures.

    Args:
        context: Analysis context - "all" for network-wide, or specific
                 device_id to focus on incidents affecting that device

    Returns:
        JSON object with:
        - root_causes: List of identified root causes with confidence scores
        - causal_graph: Graph structure showing cause/effect relationships
        - affected_devices: List of devices impacted by the incident
        - timeline: Chronological event timeline
        - explanation: Human-readable incident summary
    """
    from mcp_network.causal import build_causal_graph, identify_root_causes, AnomalyEvent

    # Snapshot current metrics to get latest anomalies
    _snapshot_metrics()

    # Collect all recent anomalies
    anomaly_config = _get_anomaly_config()
    all_events = []

    network = get_network()
    for device_id, device in network.devices.items():
        # Skip if context is specific and doesn't match
        if context != "all" and device_id != context:
            continue

        # Check CPU
        cpu_series = _metric_store.get_series(device_id, "cpu")
        if cpu_series and len(cpu_series.samples) >= anomaly_config["min_samples"]:
            cpu_anomalies = detect_all_anomalies(cpu_series, "cpu", **anomaly_config)
            for anom in cpu_anomalies:
                all_events.append(AnomalyEvent(
                    device_id=device_id,
                    metric="cpu",
                    anomaly_type=anom.anomaly_type,
                    timestamp=cpu_series.samples[-1].timestamp,
                    severity=anom.severity,
                    score=anom.score,
                ))

        # Check interfaces
        for iface in device.interfaces:
            util_series = _metric_store.get_series(device_id, f"{iface.name}_utilization")
            if util_series and len(util_series.samples) >= anomaly_config["min_samples"]:
                util_anomalies = detect_all_anomalies(util_series, f"{iface.name}_utilization", **anomaly_config)
                for anom in util_anomalies:
                    all_events.append(AnomalyEvent(
                        device_id=device_id,
                        metric=f"{iface.name}_utilization",
                        anomaly_type=anom.anomaly_type,
                        timestamp=util_series.samples[-1].timestamp,
                        severity=anom.severity,
                        score=anom.score,
                    ))

            err_series = _metric_store.get_series(device_id, f"{iface.name}_errors")
            if err_series and len(err_series.samples) >= anomaly_config["min_samples"]:
                err_anomalies = detect_all_anomalies(err_series, f"{iface.name}_errors", **anomaly_config)
                for anom in err_anomalies:
                    all_events.append(AnomalyEvent(
                        device_id=device_id,
                        metric=f"{iface.name}_errors",
                        anomaly_type=anom.anomaly_type,
                        timestamp=err_series.samples[-1].timestamp,
                        severity=anom.severity,
                        score=anom.score,
                    ))

    if not all_events:
        return json.dumps({
            "root_causes": [],
            "affected_devices": [],
            "timeline": [],
            "explanation": "No anomalies detected in recent data.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, indent=2)

    # Build causal graph
    causal_graph = build_causal_graph(all_events, network.graph, max_time_window_seconds=300.0)

    # Identify root causes
    root_causes = identify_root_causes(causal_graph, min_confidence=0.4)

    # Format results
    root_cause_list = []
    for rc in root_causes:
        root_cause_list.append({
            "device_id": rc.root_event.device_id,
            "metric": rc.root_event.metric,
            "anomaly_type": rc.root_event.anomaly_type,
            "confidence": round(rc.confidence, 3),
            "impact_score": round(rc.impact_score, 2),
            "affected_devices": rc.affected_devices,
            "evidence": rc.evidence,
            "explanation": rc.explanation,
        })

    # Build timeline
    timeline = []
    for event in sorted(all_events, key=lambda e: e.timestamp):
        timeline.append({
            "timestamp": datetime.fromtimestamp(event.timestamp, timezone.utc).isoformat(),
            "device_id": event.device_id,
            "metric": event.metric,
            "anomaly_type": event.anomaly_type,
            "severity": event.severity,
        })

    # Causal graph structure
    graph_edges = []
    for edge in causal_graph.edges:
        graph_edges.append({
            "cause": edge.cause_event.event_id,
            "effect": edge.effect_event.event_id,
            "confidence": round(edge.confidence, 3),
            "time_delta_seconds": round(edge.time_delta_seconds, 1),
            "evidence": edge.evidence,
        })

    affected_devices = list(set(e.device_id for e in all_events))

    # Generate explanation
    if root_causes:
        top_root = root_causes[0]
        explanation = (
            f"Incident analysis: {len(all_events)} anomaly events detected across "
            f"{len(affected_devices)} devices. Most likely root cause: "
            f"{top_root.root_event.device_id} {top_root.root_event.metric} "
            f"({top_root.confidence:.0%} confidence). "
            f"Affected {len(top_root.affected_devices)} devices."
        )
    else:
        explanation = (
            f"{len(all_events)} anomaly events detected but no clear root cause identified. "
            "Events may be independent or correlation confidence is low."
        )

    return json.dumps({
        "root_causes": root_cause_list,
        "causal_graph": {
            "events": len(all_events),
            "edges": graph_edges,
        },
        "affected_devices": affected_devices,
        "timeline": timeline,
        "explanation": explanation,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, indent=2)


# ============================================================================
# Consumer Mode: Edge Diagnostics (No Credentials Required)
# ============================================================================

@mcp.tool()
async def why_is_it_slow(destination: str) -> str:
    """
    Diagnose why a destination (website, server, etc.) is slow.

    No device credentials needed — runs diagnostic probes from your computer.
    Tests your local network, ISP connection, and path to the destination.

    Use this when you're experiencing slowness and want to know where the
    problem is: your WiFi, your router, your ISP, or the destination itself.

    Args:
        destination: URL, hostname, or IP (e.g., "zoom.us", "8.8.8.8", "https://google.com")

    Returns:
        JSON with diagnosis, bottleneck identification, and suggestions
    """
    from mcp_network.collectors.edge import EdgeCollector

    collector = EdgeCollector()

    try:
        probe = await collector.probe_destination(destination)
    except Exception as e:
        return json.dumps({
            "error": f"Probe failed: {e}",
            "destination": destination,
        }, indent=2)

    # Analyze results to identify bottleneck (with external context)
    diagnosis = await _analyze_edge_probe(probe)

    return json.dumps(diagnosis, indent=2)


@mcp.tool()
async def check_my_connection() -> str:
    """
    Quick health check of your internet connection.

    Tests multiple layers:
    - WiFi signal (if applicable)
    - Local gateway (your router)
    - DNS resolution
    - External connectivity

    Returns status for each layer with any issues identified.

    Returns:
        JSON with health status for each network layer
    """
    from mcp_network.collectors.edge import EdgeCollector

    collector = EdgeCollector()

    # Test gateway
    gateway = await collector._probe_gateway()

    # Test DNS
    dns_google = await collector._probe_dns("google.com")
    dns_cloudflare = await collector._probe_dns("one.one.one.one")

    # Test external ping
    external_latency, external_loss = await collector._ping("8.8.8.8", count=5)

    # Get WiFi stats
    wifi = await collector._get_wifi_stats()

    # Determine overall health
    issues = []
    if wifi and wifi.quality in ("poor", "fair"):
        issues.append(f"WiFi signal is {wifi.quality} ({wifi.signal_strength_dbm} dBm)")

    if gateway.status != "healthy":
        issues.append(f"Local network {gateway.status} (gateway: {gateway.latency_ms:.1f}ms, {gateway.loss_pct}% loss)")

    if dns_google.resolution_ms < 0 or dns_cloudflare.resolution_ms < 0:
        issues.append("DNS resolution failing")
    elif max(dns_google.resolution_ms, dns_cloudflare.resolution_ms) > 100:
        issues.append(f"DNS slow ({max(dns_google.resolution_ms, dns_cloudflare.resolution_ms):.0f}ms)")

    if external_loss > 5.0:
        issues.append(f"Internet connection unstable ({external_loss}% packet loss)")
    elif external_latency > 50.0:
        issues.append(f"Internet latency high ({external_latency:.0f}ms)")

    overall_status = "healthy" if not issues else "degraded"

    return json.dumps({
        "overall_status": overall_status,
        "issues": issues,
        "layers": {
            "wifi": {
                "available": wifi is not None,
                "ssid": wifi.ssid if wifi else None,
                "signal_strength_dbm": wifi.signal_strength_dbm if wifi else None,
                "quality": wifi.quality if wifi else None,
            },
            "local_network": {
                "gateway_ip": gateway.ip,
                "latency_ms": round(gateway.latency_ms, 1),
                "loss_pct": round(gateway.loss_pct, 1),
                "status": gateway.status,
            },
            "dns": {
                "google_ms": round(dns_google.resolution_ms, 1) if dns_google.resolution_ms > 0 else "failed",
                "cloudflare_ms": round(dns_cloudflare.resolution_ms, 1) if dns_cloudflare.resolution_ms > 0 else "failed",
            },
            "internet": {
                "latency_to_8888_ms": round(external_latency, 1),
                "packet_loss_pct": round(external_loss, 1),
            },
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, indent=2)


@mcp.tool()
async def trace_path(destination: str) -> str:
    """
    Show the network path to a destination with latency per hop.

    Identifies which segment of the path has issues:
    - Hops 1-2: Your local network/router
    - Hops 3-5: Your ISP's network
    - Later hops: Transit networks and destination

    Args:
        destination: Hostname or IP to trace

    Returns:
        JSON with hop-by-hop breakdown and bottleneck identification
    """
    from mcp_network.collectors.edge import EdgeCollector

    collector = EdgeCollector()

    try:
        hops = await collector._run_traceroute(destination)
    except Exception as e:
        return json.dumps({
            "error": f"Traceroute failed: {e}",
            "destination": destination,
        }, indent=2)

    if not hops:
        return json.dumps({
            "error": "No traceroute data collected",
            "destination": destination,
            "hint": "Ensure traceroute/mtr is installed and accessible",
        }, indent=2)

    # Identify bottleneck (highest latency jump)
    bottleneck_hop = None
    max_jump = 0.0

    for i in range(1, len(hops)):
        jump = hops[i].latency_ms - hops[i-1].latency_ms
        if jump > max_jump:
            max_jump = jump
            bottleneck_hop = hops[i]

    # Format hop list
    hop_list = []
    for hop in hops:
        hop_list.append({
            "number": hop.number,
            "ip": hop.ip,
            "hostname": hop.hostname,
            "latency_ms": round(hop.latency_ms, 1),
            "loss_pct": round(hop.loss_pct, 1) if hop.loss_pct else 0.0,
            "is_bottleneck": hop == bottleneck_hop,
        })

    # Classify segment
    if bottleneck_hop:
        if bottleneck_hop.number <= 2:
            segment = "local_network"
            explanation = "The bottleneck is in your local network (WiFi or router)"
        elif bottleneck_hop.number <= 5:
            segment = "isp"
            explanation = "The bottleneck is inside your ISP's network"
        else:
            segment = "internet"
            explanation = "The bottleneck is in the internet path or at the destination"
    else:
        segment = "unknown"
        explanation = "Path looks healthy overall"

    return json.dumps({
        "destination": destination,
        "hops": hop_list,
        "bottleneck": {
            "hop_number": bottleneck_hop.number if bottleneck_hop else None,
            "ip": bottleneck_hop.ip if bottleneck_hop else None,
            "latency_ms": round(bottleneck_hop.latency_ms, 1) if bottleneck_hop else None,
            "latency_jump_ms": round(max_jump, 1) if bottleneck_hop else None,
            "segment": segment,
            "explanation": explanation,
        },
        "total_latency_ms": round(hops[-1].latency_ms, 1) if hops else 0.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, indent=2)


async def _analyze_edge_probe(probe) -> dict:
    """Analyze edge probe results and generate diagnosis with external context."""
    from mcp_network.context import BGPContext, OutageContext

    bgp_ctx = BGPContext()
    outage_ctx = OutageContext()

    issues = []
    bottleneck = "unknown"
    confidence = 0.0
    context_notes = []

    # Check WiFi
    if probe.wifi and probe.wifi.quality in ("poor", "fair"):
        issues.append(f"WiFi signal is {probe.wifi.quality} ({probe.wifi.signal_strength_dbm} dBm)")
        if probe.wifi.quality == "poor":
            bottleneck = "wifi"
            confidence = 0.85

    # Check gateway
    if probe.gateway.status != "healthy":
        issues.append(f"Local network {probe.gateway.status} ({probe.gateway.latency_ms:.0f}ms to gateway)")
        if bottleneck == "unknown":
            bottleneck = "local_network"
            confidence = 0.80

    # Check DNS
    if probe.dns and probe.dns.resolution_ms > 100:
        issues.append(f"DNS resolution slow ({probe.dns.resolution_ms:.0f}ms)")

    # Analyze traceroute for ISP or internet issues with AS lookup
    if probe.traceroute and len(probe.traceroute) > 2:
        # Find biggest latency jump
        max_jump = 0.0
        problem_hop = None

        for i in range(1, len(probe.traceroute)):
            jump = probe.traceroute[i].latency_ms - probe.traceroute[i-1].latency_ms
            if jump > max_jump and jump > 20:  # Significant jump threshold
                max_jump = jump
                problem_hop = probe.traceroute[i]

        if problem_hop and problem_hop.ip:
            # Enrich with BGP/AS context
            as_info = await bgp_ctx.get_as_info(problem_hop.ip)

            # Check if this AS has known outages
            if as_info.asn:
                outage_status = await outage_ctx.correlate_with_as(as_info.asn)
                if outage_status:
                    context_notes.append(outage_status)

            # Format issue with network owner info
            hop_description = bgp_ctx.format_as_info(as_info)

            if problem_hop.number <= 5:
                issues.append(f"ISP network slow at hop {problem_hop.number}: {hop_description}")
                if bottleneck == "unknown":
                    bottleneck = "isp_internal"
                    confidence = 0.75
            else:
                provider_name = outage_ctx.is_known_provider_as(as_info.asn)
                if provider_name:
                    issues.append(f"{provider_name} network slow at hop {problem_hop.number}")
                    context_notes.append(f"Traffic routing through {provider_name} (AS{as_info.asn})")
                else:
                    issues.append(f"Internet path slow at hop {problem_hop.number}: {hop_description}")

                if bottleneck == "unknown":
                    bottleneck = "internet_path"
                    confidence = 0.70

    # Check HTTP timing if available
    if probe.http:
        if probe.http.dns_ms > 100:
            issues.append(f"DNS lookup slow ({probe.http.dns_ms:.0f}ms)")
        if probe.http.tls_ms > 200:
            issues.append(f"TLS handshake slow ({probe.http.tls_ms:.0f}ms)")
        if probe.http.ttfb_ms > 500:
            issues.append(f"Server response slow ({probe.http.ttfb_ms:.0f}ms)")
            if bottleneck == "unknown":
                bottleneck = "destination"
                confidence = 0.80

    # Generate summary
    if not issues:
        summary = f"Connection to {probe.target} appears healthy"
        bottleneck = "none"
        confidence = 0.90
    else:
        summary = f"Found {len(issues)} issue(s) affecting {probe.target}"

    # Generate suggestions
    suggestions = _generate_suggestions(bottleneck, probe)

    result = {
        "destination": probe.target,
        "diagnosis": {
            "bottleneck": bottleneck,
            "confidence": round(confidence, 2),
            "summary": summary,
        },
        "issues": issues,
        "suggestions": suggestions,
        "path_analysis": {
            "wifi": {
                "status": probe.wifi.quality if probe.wifi else "not_wifi",
                "signal_dbm": probe.wifi.signal_strength_dbm if probe.wifi else None,
            },
            "local_network": {
                "status": probe.gateway.status,
                "latency_ms": round(probe.gateway.latency_ms, 1),
            },
            "dns": {
                "resolution_ms": round(probe.dns.resolution_ms, 1) if probe.dns else None,
            },
            "path_hops": len(probe.traceroute),
            "total_latency_ms": round(probe.traceroute[-1].latency_ms, 1) if probe.traceroute else None,
        },
        "timestamp": datetime.fromtimestamp(probe.timestamp, timezone.utc).isoformat(),
    }

    # Add context notes if any
    if context_notes:
        result["context"] = context_notes

    return result


def _generate_suggestions(bottleneck: str, probe) -> list[str]:
    """Generate actionable suggestions based on bottleneck."""
    suggestions = []

    if bottleneck == "wifi":
        suggestions.extend([
            "Move closer to your WiFi router",
            "Switch to 5GHz network if available",
            "Use wired Ethernet connection if possible",
            "Check for interference from other devices",
        ])
    elif bottleneck == "local_network":
        suggestions.extend([
            "Restart your router",
            "Check if other devices are using bandwidth",
            "Try wired connection instead of WiFi",
            f"Contact network admin (gateway: {probe.gateway.ip})",
        ])
    elif bottleneck == "isp_internal":
        suggestions.extend([
            "This issue is inside your ISP's network — outside your control",
            "Check downdetector.com for reported ISP outages",
            "Try mobile hotspot as temporary workaround",
            "Report persistent issues to your ISP",
        ])
    elif bottleneck == "internet_path":
        suggestions.extend([
            "The slowdown is in the internet path to destination",
            "Try again later — may be temporary congestion",
            "Try using a VPN to different geographic region",
            "Check if destination has status page for outages",
        ])
    elif bottleneck == "destination":
        suggestions.extend([
            "The destination server appears slow",
            "Check destination's status page for known issues",
            "Try different server/region if available",
            "Your network path is healthy — issue is with the service",
        ])
    else:
        suggestions.append("Connection appears healthy overall")

    return suggestions


# ============================================================================
# Consumer Mode: Baseline & History (Phase 2)
# ============================================================================

# Module-level baseline storage
_baseline_storage = None


def _get_baseline_storage():
    """Get or create baseline storage singleton."""
    global _baseline_storage
    if _baseline_storage is None:
        from mcp_network.baseline import BaselineStorage
        _baseline_storage = BaselineStorage()
    return _baseline_storage


@mcp.tool()
async def record_baseline() -> str:
    """
    Record current network state as baseline measurement.

    Run this when your connection is working well to establish a baseline.
    The system will automatically track historical "good" performance over time.

    Recommended: Run this tool 5-10 times over a few days during normal usage
    to build a reliable baseline.

    Returns:
        JSON confirmation with recorded metrics
    """
    from mcp_network.collectors.edge import EdgeCollector
    from mcp_network.baseline import BaselineSnapshot

    collector = EdgeCollector()
    storage = _get_baseline_storage()

    # Collect current state
    gateway = await collector._probe_gateway()
    dns = await collector._probe_dns("google.com")
    external_latency, external_loss = await collector._ping("8.8.8.8", count=5)
    wifi = await collector._get_wifi_stats()

    # Create snapshot
    snapshot = BaselineSnapshot(
        timestamp=time.time(),
        gateway_latency_ms=gateway.latency_ms,
        gateway_loss_pct=gateway.loss_pct,
        dns_resolution_ms=dns.resolution_ms if dns.resolution_ms > 0 else 0.0,
        external_latency_ms=external_latency,
        external_loss_pct=external_loss,
        wifi_signal_dbm=wifi.signal_strength_dbm if wifi else None,
        wifi_quality=wifi.quality if wifi else None,
    )

    storage.add_snapshot(snapshot)

    return json.dumps({
        "status": "baseline_recorded",
        "metrics": {
            "gateway_latency_ms": round(snapshot.gateway_latency_ms, 1),
            "gateway_loss_pct": round(snapshot.gateway_loss_pct, 1),
            "dns_resolution_ms": round(snapshot.dns_resolution_ms, 1),
            "external_latency_ms": round(snapshot.external_latency_ms, 1),
            "external_loss_pct": round(snapshot.external_loss_pct, 1),
            "wifi_signal_dbm": snapshot.wifi_signal_dbm,
        },
        "total_baseline_samples": len(storage.snapshots),
        "timestamp": datetime.fromtimestamp(snapshot.timestamp, timezone.utc).isoformat(),
    }, indent=2)


@mcp.tool()
async def compare_to_baseline() -> str:
    """
    Compare current network performance to historical baseline.

    Shows how current metrics deviate from normal:
    - "Gateway latency: 45ms (normally 8ms, 5.6x worse)"
    - "WiFi signal: -72 dBm (normally -52 dBm, 38% worse)"

    Requires at least 5 baseline samples. Run record_baseline() first.

    Returns:
        JSON with per-metric comparison and anomaly flags
    """
    from mcp_network.collectors.edge import EdgeCollector
    from mcp_network.baseline import BaselineSnapshot

    collector = EdgeCollector()
    storage = _get_baseline_storage()

    # Check if we have enough baseline data
    if len(storage.snapshots) < 5:
        return json.dumps({
            "error": "Insufficient baseline data",
            "current_samples": len(storage.snapshots),
            "required_samples": 5,
            "hint": "Run record_baseline() at least 5 times to establish a baseline",
        }, indent=2)

    # Collect current state
    gateway = await collector._probe_gateway()
    dns = await collector._probe_dns("google.com")
    external_latency, external_loss = await collector._ping("8.8.8.8", count=5)
    wifi = await collector._get_wifi_stats()

    # Create current snapshot
    current = BaselineSnapshot(
        timestamp=time.time(),
        gateway_latency_ms=gateway.latency_ms,
        gateway_loss_pct=gateway.loss_pct,
        dns_resolution_ms=dns.resolution_ms if dns.resolution_ms > 0 else 0.0,
        external_latency_ms=external_latency,
        external_loss_pct=external_loss,
        wifi_signal_dbm=wifi.signal_strength_dbm if wifi else None,
        wifi_quality=wifi.quality if wifi else None,
    )

    # Compare to baseline
    comparisons = storage.compare_to_baseline(current)

    # Format results
    comparison_list = []
    anomalies = []

    for comp in comparisons:
        comparison_list.append({
            "metric": comp.metric,
            "current": round(comp.current_value, 2),
            "baseline_mean": round(comp.baseline_mean, 2),
            "baseline_stddev": round(comp.baseline_stddev, 2),
            "deviation_factor": round(comp.deviation_factor, 2),
            "severity": comp.severity,
            "explanation": comp.explanation,
        })

        if comp.is_anomalous:
            anomalies.append({
                "metric": comp.metric,
                "severity": comp.severity,
                "explanation": comp.explanation,
            })

    # Overall assessment
    if not anomalies:
        overall = "normal"
        summary = "All metrics within normal range"
    elif any(a["severity"] == "critical" for a in anomalies):
        overall = "critical"
        summary = f"{len(anomalies)} critical anomalies detected"
    else:
        overall = "warning"
        summary = f"{len(anomalies)} anomalies detected"

    return json.dumps({
        "overall_status": overall,
        "summary": summary,
        "anomalies": anomalies,
        "comparisons": comparison_list,
        "baseline_samples": len(storage.snapshots),
        "timestamp": datetime.fromtimestamp(current.timestamp, timezone.utc).isoformat(),
    }, indent=2)


@mcp.tool()
async def clear_baseline() -> str:
    """
    Clear all baseline data and start fresh.

    Use this if network conditions have permanently changed (e.g., ISP upgrade)
    and you want to establish a new baseline.

    Returns:
        JSON confirmation
    """
    storage = _get_baseline_storage()
    storage.clear_baseline()

    return json.dumps({
        "status": "baseline_cleared",
        "message": "All baseline data has been cleared. Run record_baseline() to start fresh.",
    }, indent=2)


@mcp.tool()
async def run_speedtest() -> str:
    """
    Run a bandwidth speed test to measure download/upload speeds.

    Uses speedtest-cli if available, otherwise provides installation instructions.
    Tests both download and upload speeds to measure actual bandwidth.

    Note: This test transfers data and may take 30-60 seconds to complete.

    Returns:
        JSON with download/upload speeds in Mbps, ping, and server info
    """
    # Check if speedtest-cli is installed
    try:
        proc = await asyncio.create_subprocess_exec(
            "which", "speedtest-cli",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        has_speedtest = proc.returncode == 0
    except Exception:
        has_speedtest = False

    if not has_speedtest:
        return json.dumps({
            "error": "speedtest-cli not installed",
            "install_instructions": {
                "macOS": "brew install speedtest-cli",
                "Linux": "pip install speedtest-cli  OR  apt install speedtest-cli",
                "Windows": "pip install speedtest-cli",
            },
            "hint": "After installing, run this tool again to measure bandwidth",
        }, indent=2)

    try:
        # Run speedtest with JSON output
        proc = await asyncio.create_subprocess_exec(
            "speedtest-cli", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=90.0)

        if proc.returncode != 0:
            return json.dumps({
                "error": "speedtest failed",
                "stderr": stderr.decode(),
            }, indent=2)

        # Parse JSON output
        result = json.loads(stdout.decode())

        # Extract key metrics
        download_bps = result.get("download", 0)
        upload_bps = result.get("upload", 0)
        ping_ms = result.get("ping", 0)
        server = result.get("server", {})

        # Convert to Mbps
        download_mbps = download_bps / 1_000_000
        upload_mbps = upload_bps / 1_000_000

        return json.dumps({
            "download_mbps": round(download_mbps, 2),
            "upload_mbps": round(upload_mbps, 2),
            "ping_ms": round(ping_ms, 1),
            "server": {
                "name": server.get("name", "Unknown"),
                "country": server.get("country", "Unknown"),
                "sponsor": server.get("sponsor", "Unknown"),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }, indent=2)

    except asyncio.TimeoutError:
        return json.dumps({
            "error": "speedtest timed out after 90 seconds",
            "hint": "Check your internet connection and try again",
        }, indent=2)
    except json.JSONDecodeError:
        return json.dumps({
            "error": "failed to parse speedtest output",
            "hint": "speedtest-cli may be outdated. Try: pip install --upgrade speedtest-cli",
        }, indent=2)
    except Exception as e:
        return json.dumps({
            "error": f"speedtest failed: {e}",
        }, indent=2)


# ============================================================================
# Agent Control Tools
# ============================================================================

# Module-level agent instance (singleton)
_agent_instance = None


@mcp.tool()
async def start_agent(poll_interval_seconds: int = 60) -> str:
    """
    Start the continuous network monitoring agent.

    The agent will:
    - Monitor network conditions every poll_interval_seconds
    - Check registered intents against current state
    - Diagnose violations and take action (alert, record)
    - Update baselines automatically

    Args:
        poll_interval_seconds: Time between monitoring checks (default 60)

    Returns:
        JSON with agent status
    """
    from mcp_network.agent import NetworkAgent, AgentConfig

    global _agent_instance

    if _agent_instance and _agent_instance.running:
        return json.dumps({
            "status": "already_running",
            "intents_count": len(_agent_instance.get_intents()),
            "poll_interval": _agent_instance.config.poll_interval,
        }, indent=2)

    config = AgentConfig(poll_interval=float(poll_interval_seconds))
    _agent_instance = NetworkAgent(config)
    await _agent_instance.start()

    return json.dumps({
        "status": "started",
        "poll_interval": poll_interval_seconds,
        "intents_count": 0,
        "message": "Agent is now monitoring. Add intents with set_intent().",
    }, indent=2)


@mcp.tool()
async def stop_agent() -> str:
    """
    Stop the continuous network monitoring agent.

    Returns:
        JSON with final status
    """
    global _agent_instance

    if not _agent_instance or not _agent_instance.running:
        return json.dumps({
            "status": "not_running",
            "message": "Agent is not currently running",
        }, indent=2)

    intents_count = len(_agent_instance.get_intents())
    incidents_count = len(_agent_instance.get_incidents())

    await _agent_instance.stop()

    return json.dumps({
        "status": "stopped",
        "intents_monitored": intents_count,
        "incidents_detected": incidents_count,
    }, indent=2)


@mcp.tool()
async def set_intent(goal: str, priority: int = 5) -> str:
    """
    Add a network monitoring goal in natural language.

    The agent will parse your goal and monitor for violations.

    Examples:
    - "Zoom calls should never lag"
      → Monitors zoom.us latency < 100ms
    - "Alert me if gaming latency exceeds 50ms"
      → Alerts when gaming latency > 50ms
    - "My connection should stay close to baseline"
      → Monitors for baseline deviation > 2x

    Args:
        goal: Your network goal in plain English
        priority: 1-10, higher = more important (default 5)

    Returns:
        JSON with parsed intent details
    """
    from mcp_network.agent import IntentParser

    global _agent_instance

    # Parse the intent
    parser = IntentParser()
    intent = await parser.parse(goal)
    intent.priority = priority

    # Start agent if not running
    if not _agent_instance or not _agent_instance.running:
        from mcp_network.agent import NetworkAgent, AgentConfig
        _agent_instance = NetworkAgent(AgentConfig())
        await _agent_instance.start()

    # Add to agent
    _agent_instance.add_intent(intent)

    return json.dumps({
        "status": "intent_added",
        "intent": {
            "id": intent.id,
            "name": intent.name,
            "target": intent.target,
            "metric": intent.metric,
            "threshold": intent.threshold,
            "comparison": intent.comparison,
            "priority": intent.priority,
            "actions": intent.actions,
        },
        "message": f"Now monitoring: {intent.name}",
    }, indent=2)


@mcp.tool()
async def list_intents() -> str:
    """
    List all registered monitoring intents.

    Returns:
        JSON with all active intents
    """
    global _agent_instance

    if not _agent_instance:
        return json.dumps({
            "intents": [],
            "message": "Agent not initialized. Use set_intent() to start.",
        }, indent=2)

    intents = _agent_instance.get_intents()

    return json.dumps({
        "intents": [
            {
                "id": i.id,
                "name": i.name,
                "target": i.target,
                "metric": i.metric,
                "threshold": i.threshold,
                "comparison": i.comparison,
                "priority": i.priority,
                "actions": i.actions,
                "enabled": i.enabled,
            }
            for i in intents
        ],
        "count": len(intents),
        "agent_running": _agent_instance.running,
    }, indent=2)


@mcp.tool()
async def remove_intent(intent_id: str) -> str:
    """
    Remove a monitoring intent by ID.

    Args:
        intent_id: The intent ID to remove (from list_intents)

    Returns:
        JSON with removal status
    """
    global _agent_instance

    if not _agent_instance:
        return json.dumps({
            "status": "error",
            "message": "Agent not initialized",
        }, indent=2)

    _agent_instance.remove_intent(intent_id)

    return json.dumps({
        "status": "removed",
        "intent_id": intent_id,
        "remaining_intents": len(_agent_instance.get_intents()),
    }, indent=2)


@mcp.tool()
async def get_incidents(limit: int = 10) -> str:
    """
    Get recent network incidents detected by the agent.

    Args:
        limit: Maximum number of incidents to return (default 10)

    Returns:
        JSON with recent incidents
    """
    global _agent_instance

    if not _agent_instance:
        return json.dumps({
            "incidents": [],
            "message": "Agent not initialized",
        }, indent=2)

    incidents = _agent_instance.get_incidents(limit=limit)

    return json.dumps({
        "incidents": [
            {
                "id": inc.id,
                "intent_id": inc.intent_id,
                "timestamp": inc.timestamp.isoformat(),
                "metric": inc.metric,
                "target": inc.target,
                "current_value": inc.current_value,
                "threshold": inc.threshold,
                "severity": inc.severity,
                "actions_taken": inc.actions_taken,
                "diagnosis": inc.diagnosis.get("verdict") if inc.diagnosis else None,
            }
            for inc in incidents
        ],
        "count": len(incidents),
        "total_incidents": len(_agent_instance.get_incidents()),
    }, indent=2)


@mcp.tool()
async def agent_status() -> str:
    """
    Get current status of the monitoring agent.

    Returns:
        JSON with agent status, uptime, and statistics
    """
    global _agent_instance

    if not _agent_instance:
        return json.dumps({
            "status": "not_initialized",
            "message": "Use start_agent() or set_intent() to begin monitoring",
        }, indent=2)

    return json.dumps({
        "status": "running" if _agent_instance.running else "stopped",
        "intents": {
            "total": len(_agent_instance.get_intents()),
            "enabled": sum(1 for i in _agent_instance.get_intents() if i.enabled),
        },
        "incidents": {
            "total": len(_agent_instance.get_incidents()),
            "recent_10": len(_agent_instance.get_incidents(limit=10)),
        },
        "config": {
            "poll_interval": _agent_instance.config.poll_interval,
            "alert_cooldown": _agent_instance.config.alert_cooldown,
        },
    }, indent=2)


# ============================================================================
# Autonomous Agent Tools (Leap 3)
# ============================================================================

# Module-level autonomous agent instance
_autonomous_agent = None


@mcp.tool()
async def plan_goal(goal: str) -> str:
    """
    Generate an action plan for a natural language network goal.

    The autonomous planner converts your high-level goal into concrete actions
    with safety guardrails. This lets you see the plan before committing.

    Examples:
    - "Keep Zoom responsive during work hours"
    - "Investigate whenever Netflix buffers"
    - "Alert me if my connection degrades from baseline"
    - "Ensure gaming never exceeds 50ms"

    Args:
        goal: Your network goal in plain English

    Returns:
        JSON with generated action plan, confidence, and explanation
    """
    from mcp_network.agent import AutonomousAgent
    import hashlib

    global _autonomous_agent

    if not _autonomous_agent:
        _autonomous_agent = AutonomousAgent()

    # Generate intent ID
    intent_id = hashlib.md5(goal.encode()).hexdigest()[:12]

    # Generate plan
    plan = await _autonomous_agent.set_goal(goal, intent_id)

    return json.dumps({
        "goal": goal,
        "intent_id": intent_id,
        "confidence": plan.confidence,
        "explanation": plan.explanation,
        "actions": [
            {
                "type": action.type,
                "target": action.target,
                "metric": action.metric,
                "threshold": action.threshold,
                "comparison": action.comparison,
                "interval_seconds": action.interval_seconds,
                "params": action.params,
            }
            for action in plan.actions
        ],
        "triggers": plan.triggers,
        "guardrails": plan.guardrails,
        "next_step": "Use execute_plan() to activate this plan",
    }, indent=2)


@mcp.tool()
async def execute_plan(intent_id: str) -> str:
    """
    Execute a previously generated action plan.

    This activates the plan and starts monitoring according to the actions.

    Args:
        intent_id: The intent ID from plan_goal()

    Returns:
        JSON with execution status
    """
    from mcp_network.agent import NetworkAgent, AgentConfig

    global _autonomous_agent, _agent_instance

    if not _autonomous_agent:
        return json.dumps({
            "status": "error",
            "message": "No plans generated. Use plan_goal() first.",
        }, indent=2)

    plan = _autonomous_agent.get_plan(intent_id)
    if not plan:
        return json.dumps({
            "status": "error",
            "message": f"Plan {intent_id} not found. Use plan_goal() first.",
        }, indent=2)

    # Start agent if not running
    if not _agent_instance or not _agent_instance.running:
        _agent_instance = NetworkAgent(AgentConfig())
        await _agent_instance.start()

    # Convert plan to intent (simplified - just use first monitor action)
    from mcp_network.agent import Intent
    monitor_action = next((a for a in plan.actions if a.type == "monitor"), None)

    if monitor_action:
        intent = Intent(
            id=intent_id,
            name=plan.goal[:50],  # Truncate for display
            target=monitor_action.target or "all",
            metric=monitor_action.metric or "latency",
            threshold=monitor_action.threshold or 100.0,
            comparison=monitor_action.comparison or "<",
            priority=5,
            actions=[a.type for a in plan.actions if a.type in ["alert", "diagnose", "record"]],
        )

        _agent_instance.add_intent(intent)

        return json.dumps({
            "status": "executed",
            "intent_id": intent_id,
            "goal": plan.goal,
            "monitoring": f"{intent.target} {intent.metric}",
            "message": "Plan activated. Agent is now monitoring.",
        }, indent=2)
    else:
        return json.dumps({
            "status": "error",
            "message": "Plan has no monitor action",
        }, indent=2)


@mcp.tool()
async def get_guardrail_status() -> str:
    """
    Get current guardrail enforcement status.

    Shows rate limits, cooldowns, and any disabled intents.

    Returns:
        JSON with guardrail state
    """
    global _autonomous_agent

    if not _autonomous_agent:
        return json.dumps({
            "message": "Autonomous agent not initialized",
        }, indent=2)

    status = _autonomous_agent.get_guardrail_status()

    return json.dumps({
        "guardrails": status,
        "message": "Guardrails protect against excessive alerts and actions",
    }, indent=2)
