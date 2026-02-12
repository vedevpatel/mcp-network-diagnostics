"""MCP Network Diagnostics - AI-powered network troubleshooting."""
__version__ = "0.1.0"

from mcp_network.tools import (
    check_my_connection,
    why_is_it_slow,
    trace_path,
    record_baseline,
    compare_to_baseline,
    get_device_status,
    diagnose_latency,
    list_devices,
)
from mcp_network.agent.core import NetworkAgent

__all__ = [
    "check_my_connection",
    "why_is_it_slow",
    "trace_path",
    "record_baseline",
    "compare_to_baseline",
    "get_device_status",
    "diagnose_latency",
    "list_devices",
    "NetworkAgent",
]