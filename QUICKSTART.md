# Quick Start Guide

Get up and running with MCP Network Diagnostics in 5 minutes.

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/mcp-network-diagnostics.git
cd mcp-network-diagnostics

# Install with uv (recommended)
uv pip install -e .

# Or with pip
pip install -e .
```

## Option 1: Demo with Simulated Network (Fastest)

Perfect for understanding the tools without any hardware.

```bash
# Start the server
mcp-network --collector simulated

# In another terminal, test it
python -c "
import asyncio
from mcp_network.tools import detect_anomalies, explain_incident

async def demo():
    # Generate some data
    for _ in range(15):
        print(await detect_anomalies())

    # Run incident analysis
    print(await explain_incident())

asyncio.run(demo())
"
```

The simulated network includes:
- 10 routers in a mesh topology
- Injected anomalies (R2 CPU spike, R5 errors, R7 volatility)
- Config changes (R3 logging change at iteration 10)

## Option 2: DevNet Always-On Sandbox (Real Cisco Device)

Test against a real Cisco IOS XE device without any setup.

```bash
# Start server with DevNet sandbox
mcp-network --collector ssh --topology-file examples/devnet_always_on.yaml

# The server connects to sandbox-iosxe-latest-1.cisco.com
# Credentials are pre-configured in the example file
```

### Configure Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "network-diagnostics": {
      "command": "/path/to/uv",
      "args": [
        "--directory",
        "/path/to/mcp-network-diagnostics",
        "run",
        "mcp-network",
        "--collector",
        "ssh",
        "--topology-file",
        "examples/devnet_always_on.yaml"
      ]
    }
  }
}
```

Restart Claude Desktop, then try:
- "List all network devices"
- "Check the collection health"
- "Get the status of cat8kv"
- "Collect device configs and check for changes"

## Available Tools

### Basic Diagnostics
- `list_devices()` - Show all devices in topology
- `get_device_status(device_id)` - CPU, memory, interfaces, trends, anomalies
- `diagnose_latency(src, dst)` - Find bottlenecks in a path

### Trend Analysis (P0)
- Predicts threshold breaches: "CPU will reach 90% in 8 minutes"
- Shows rate of change and acceleration
- Confidence levels based on data quality

### Anomaly Detection (P1)
- `detect_anomalies()` - Network-wide statistical anomaly scan
- Z-score, rate-shift, and volatility detection
- Multi-metric correlation (systemic issues)

### Collection Health (P2a)
- `get_collection_health()` - Data quality dashboard
- Shows reachability, staleness, failure rates
- Quality score: 0.0 (no data) to 1.0 (perfect)

### Config Tracking (P2b)
- `collect_device_configs()` - Snapshot all device configs (SSH only)
- `get_config_history(device_id)` - Recent changes with timestamps
- `compare_configs(device_id, time_a, time_b)` - Diff between snapshots
- `check_config_correlation(device_id)` - Did config change recently?

### Root Cause Analysis (P2c)
- `explain_incident(context="all")` - Causal analysis with confidence scores
- Temporal ordering: which anomaly appeared first?
- Topological analysis: are devices connected?
- Impact scoring: how many devices affected?

## Example Workflows

### 1. Investigate High CPU

```python
# Check current status
status = await get_device_status("R3")

# Is it anomalous?
anomalies = await detect_anomalies()

# Did config change recently?
correlation = await check_config_correlation("R3", window_seconds=1800)

# If yes, compare before/after
if correlation["had_recent_change"]:
    changes = correlation["changes"]
    time_before = changes[0]["timestamp"]
    time_after = current_time
    diff = await compare_configs("R3", time_before, time_after)
```

### 2. Network-Wide Incident Analysis

```python
# Detect all anomalies
anomalies = await detect_anomalies()

# If anomalies found, run root cause analysis
if anomalies["anomalies"]:
    incident = await explain_incident()

    # incident contains:
    # - root_causes: ranked by confidence
    # - timeline: chronological events
    # - causal_graph: cause→effect relationships
    # - affected_devices: list of impacted devices
```

### 3. Periodic Health Monitoring

```python
# Check collection quality
health = await get_collection_health()

if health["collection_quality_score"] < 0.7:
    print(f"Warning: Low data quality ({health['collection_quality_score']:.1%})")
    print(f"Unreachable devices: {health['unreachable_devices']}")
    print(f"Stale devices: {health['stale_devices']}")
```

## Testing

```bash
# Run full test suite
python -m pytest tests/

# Run specific test file
python -m pytest tests/test_anomaly_detection.py -v

# Run with coverage
python -m pytest tests/ --cov=src/mcp_network --cov-report=html
```

Current test coverage: **320 tests, 100% passing**

## Troubleshooting

### SSH Connection Fails

```bash
# Test connectivity manually
ssh admin@sandbox-iosxe-latest-1.cisco.com

# Check credentials in topology file
cat examples/devnet_always_on.yaml

# Enable debug logging
export LOG_LEVEL=DEBUG
mcp-network --collector ssh --topology-file examples/devnet_always_on.yaml
```

### No Anomalies Detected

The system needs at least 5 data points to establish a baseline:

```python
# Generate enough data
for _ in range(10):
    await detect_anomalies()

# Now anomalies should be detectable
result = await detect_anomalies()
```

### Simulated Anomalies Not Appearing

Anomalies are injected at specific iteration counts:
- R2 CPU spike: iterations 8-10
- R5 errors: iterations 12-13
- R7 volatility: iteration 15+

```python
# Run 15+ iterations to see all anomalies
for i in range(20):
    print(f"Iteration {i+1}")
    result = await detect_anomalies()
```

## Next Steps

- Read [P2_IMPLEMENTATION_SUMMARY.md](P2_IMPLEMENTATION_SUMMARY.md) for technical details
- See [DEVNET_SSH_INSTRUCTIONS.md](DEVNET_SSH_INSTRUCTIONS.md) for production deployment
- Check [examples/](examples/) for more topology configurations

## Getting Help

- GitHub Issues: https://github.com/yourusername/mcp-network-diagnostics/issues
- Documentation: See README.md and implementation summary
- DevNet Sandboxes: https://devnetsandbox.cisco.com/

## What's Next?

This platform is ready for:
- ✅ Customer demos using DevNet sandboxes
- ✅ Production testing in lab environments
- ✅ Open-source community contributions
- 🔄 P3 Action Layer (remediation suggestions, safe execution, preventive actions)
- 🔄 Enterprise integrations (vManage API, SNMP, Syslog, ITSM)
