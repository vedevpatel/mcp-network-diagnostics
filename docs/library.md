# Using as a Python Library

You can use `mcp-network` directly in your Python scripts without running an MCP server or client. This is useful for building custom dashboards, automation scripts, or integrating network diagnostics into other applications.

## Quick Start

```python
import asyncio
from mcp_network import check_my_connection, why_is_it_slow

async def main():
    # 1. Run a quick health check
    print("Checking connection...")
    health = await check_my_connection()
    print(health)

    # 2. Diagnose a specific target
    print("\nDiagnosing Google DNS...")
    diagnosis = await why_is_it_slow("8.8.8.8")
    print(diagnosis)

if __name__ == "__main__":
    asyncio.run(main())
```

## Available Tools

The following tools are available directly from the top-level package:

### Consumer Tools (Edge Diagnostics)
*   `check_my_connection()`: Comprehensive health check (WiFi, Gateway, DNS, Internet).
*   `why_is_it_slow(destination)`: Diagnoses latency and path issues to a target.
*   `trace_path(destination)`: Performs a traceroute with AS and provider enrichment.
*   `record_baseline()`: Records current network metrics to the local baseline.
*   `compare_to_baseline()`: Compares current metrics against historical baseline to find anomalies.

### Operator Tools (Device Management)
*   `list_devices()`: Lists all configured devices in the topology.
*   `get_device_status(device_id)`: Fetches health and metrics for a specific device.
*   `diagnose_latency(src, dst)`: performs AI-driven path diagnosis between two managed devices.

### Continuous Monitoring
*   `NetworkAgent`: The autonomous agent class for running background monitoring loops.

## Configuration

By default, the library uses environment variables for configuration.

*   `MCP_NETWORK_STDIO_MODE`: Set to `full` to allow unrestricted local tool execution.
*   `MCP_NETWORK_TOPOLOGY_FILE`: Path to your YAML topology file (for Operator tools).

```python
import os
os.environ["MCP_NETWORK_STDIO_MODE"] = "full"
```
