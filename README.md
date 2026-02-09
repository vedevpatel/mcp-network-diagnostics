# MCP Network Diagnostics

AI-powered network diagnostics with two modes: **Operator Mode** (SSH to devices) and **Consumer Mode** (edge diagnostics).

## Features

### Operator Mode (SSH/Prometheus)
Diagnose enterprise networks by connecting to routers and switches:
- Device status and metrics (CPU, memory, interface stats)
- Path finding between devices
- Trend analysis with breach prediction
- Anomaly detection (z-score, rate shifts, volatility)
- Root cause analysis with confidence scoring
- Config change correlation
- Multi-vendor support (Cisco IOS-XR, IOS-XE, NX-OS)

### Consumer Mode (Edge Diagnostics)
Diagnose your home/office network without device access:
- Gateway health checks
- DNS resolution timing
- Traceroute with hop analysis
- WiFi signal quality (macOS/Linux/Windows)
- Baseline tracking with anomaly detection
- Provider context (BGP/AS lookup, outage correlation)
- Continuous monitoring agent with intent system
- Speedtest integration

## Quick Start

### Consumer Mode (No Setup Required)

```bash
pip install mcp-network-diagnostics
mcp-network  # Defaults to consumer mode
```

**Claude Desktop:**
```json
{
  "mcpServers": {
    "network-diagnostics": {
      "command": "mcp-network"
    }
  }
}
```

**Try these:**
- `check_my_connection()` - Full network health check
- `why_is_it_slow("zoom.us")` - Diagnose latency to a target
- `trace_path("8.8.8.8")` - Traceroute with AS info
- `record_baseline()` - Start tracking normal behavior
- `compare_to_baseline()` - Detect anomalies vs baseline
- `set_intent("Zoom calls should never lag")` - Start monitoring

### Operator Mode - Simulated (Testing)

```bash
mcp-network --collector simulated
```

Generates a fake 10-router topology for demos. Try:
- `get_device_status("R1")`
- `diagnose_latency("R1", "R5")`
- `predict_trends()` - After calling `refresh_metrics()` 5+ times

### Operator Mode - SSH (DevNet Sandboxes)

```bash
export DEVNET_IOSXE_USERNAME=developer
export DEVNET_IOSXE_PASSWORD=C1sco12345
export DEVNET_NXOS_USERNAME=admin
export DEVNET_NXOS_PASSWORD=RG!_Yw200

mcp-network --collector ssh --topology-file iosxe_topology.yaml
```

**Claude Desktop:**
```json
{
  "mcpServers": {
    "network-diagnostics": {
      "command": "/path/to/uv",
      "args": [
        "--directory", "/path/to/mcp-network-diagnostics",
        "run", "mcp-network",
        "--collector", "ssh",
        "--topology-file", "/path/to/iosxe_topology.yaml"
      ],
      "env": {
        "DEVNET_IOSXE_USERNAME": "developer",
        "DEVNET_IOSXE_PASSWORD": "C1sco12345",
        "DEVNET_NXOS_USERNAME": "admin",
        "DEVNET_NXOS_PASSWORD": "RG!_Yw200"
      }
    }
  }
}
```

### Operator Mode - Prometheus

```bash
docker run -d -p 9090:9090 prom/prometheus
docker run -d -p 9100:9100 prom/node-exporter

mcp-network --collector prometheus \
  --prometheus-url http://localhost:9090 \
  --topology-file network_topology.yaml
```

## Consumer Mode Tools

| Tool | Description |
|------|-------------|
| `check_my_connection()` | Gateway ping, DNS, WiFi stats, speedtest check |
| `why_is_it_slow(target)` | Diagnose latency issues to a destination |
| `trace_path(target)` | Traceroute with AS/provider enrichment |
| `record_baseline()` | Start baseline tracking (auto-records over time) |
| `compare_to_baseline()` | Detect anomalies vs historical normal |
| `clear_baseline()` | Reset baseline data |
| `run_speedtest()` | Bandwidth test (requires speedtest-cli) |

### Continuous Monitoring Agent

Set network goals in natural language and let the agent watch for violations:

```python
# Start monitoring
set_intent("Zoom calls should never lag")
set_intent("Alert me if gaming latency exceeds 50ms")
set_intent("My connection should stay close to baseline")

# Check status
agent_status()
list_intents()

# View incidents
get_incidents()

# Stop when done
stop_agent()
```

The agent:
- Monitors every 60s (configurable)
- Parses natural language goals → structured intents
- Auto-diagnoses violations
- Tracks baselines automatically
- Alert cooldown prevents spam

## Operator Mode Tools

| Tool | Description |
|------|-------------|
| `get_device_status(device_id)` | CPU, memory, interface stats, health |
| `list_devices()` | All devices in topology |
| `diagnose_latency(src, dst)` | Intelligent path diagnosis |
| `find_path(src, dst)` | Shortest path between devices |
| `refresh_metrics()` | Update metrics (simulated collector only) |
| `predict_trends()` | Forecast metric breaches (5+ samples) |
| `detect_anomalies()` | Statistical anomaly detection |
| `analyze_root_cause(device_id, metric)` | Config change correlation |

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   MCP Server (stdio)                     │
├─────────────────────────────────────────────────────────┤
│                   Intelligence Layer                     │
│  • Path finding   • Trend analysis  • Anomaly detection │
│  • Root cause     • Intent parsing  • Context enrichment│
├─────────────────────────────────────────────────────────┤
│                    Data Collection                       │
├──────────────────┬──────────────────────────────────────┤
│  Operator Mode   │         Consumer Mode                │
│  • SSH           │  • EdgeCollector (ping/trace/DNS)    │
│  • Prometheus    │  • BaselineStorage (ring buffers)    │
│  • Simulated     │  • NetworkAgent (continuous)         │
└──────────────────┴──────────────────────────────────────┘
```

## Topology File Format

All operator mode collectors use YAML topology files:

```yaml
devices:
  - id: my-router          # Unique ID for tool calls
    type: router            # router or switch
    device_type: iosxe      # iosxr, iosxe, nxos (SSH only)
    host: 192.168.1.1
    username: ${MY_USER}    # ${VAR} = env variable
    password: ${MY_PASS}
    port: 22
    interfaces:
      - name: GigabitEthernet0/0/0
        prometheus_name: GigE0_0_0  # Prometheus only

links:
  - src_device: my-router
    src_interface: GigabitEthernet0/0/0
    dst_device: other-router
    dst_interface: GigabitEthernet1
    default_latency_ms: 2.0

thresholds:  # Optional, overrides defaults
  cpu: 80.0
  memory: 85.0
  utilization: 80.0
  errors: 100
  anomaly:
    z_score_threshold: 2.0
    rate_shift_threshold: 3.0
```

**Environment variable substitution:** `${VAR_NAME}` is replaced with `$VAR_NAME` at startup.

**`.local.yaml` convention:** Files matching `*_topology.local.yaml` are gitignored for credentials.

## Development

```bash
# Install with dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest tests/

# Type checking
mypy src/

# Linting
ruff check src/
```

## Test Coverage

- **359 tests** covering all collectors, tools, and analysis
- Unit tests for algorithms (trend, anomaly, pathfinding)
- Integration tests for MCP tools
- Cross-platform edge collector tests (macOS/Linux/Windows)

## Limitations

- **Read-only** - No device configuration changes
- **Static topology** - Define devices/links in YAML (no auto-discovery)
- **DevNet credentials** - Rotate periodically; refresh from developer.cisco.com if SSH fails
- **Consumer mode limitations** - Traceroute requires root/admin on some platforms
- **Agent persistence** - Runs within MCP server process; stops on server restart

## Project Structure

```
src/mcp_network/
├── collectors/          # Data collection backends
│   ├── simulated.py     # Fake topology for testing
│   ├── ssh.py           # Cisco SSH collector
│   ├── prometheus.py    # Prometheus metrics
│   └── edge.py          # Consumer mode diagnostics
├── graph/               # Path finding & analysis
├── trends/              # Time-series analysis
│   ├── analyzer.py      # Breach prediction
│   └── anomaly.py       # Statistical detection
├── context/             # External enrichment
│   ├── bgp.py           # AS lookup via Team Cymru
│   └── outages.py       # Provider status
├── agent/               # Continuous monitoring
│   ├── core.py          # NetworkAgent loop
│   └── intents.py       # Natural language parsing
├── baseline/            # Consumer baseline tracking
└── tools/               # MCP tool implementations
```

## Examples

### Consumer Mode Workflow

```
1. Check connection health
   → check_my_connection()

2. Diagnose a slow service
   → why_is_it_slow("netflix.com")

3. Investigate routing
   → trace_path("8.8.8.8")
   (Shows AS numbers, provider info, latency per hop)

4. Establish baseline
   → record_baseline()
   (Run check_my_connection() 5+ times over days)

5. Detect anomalies
   → compare_to_baseline()
   (Shows if current latency is 2x+ worse)

6. Continuous monitoring
   → set_intent("Zoom should stay under 100ms")
   → agent_status()  # Check every minute
```

### Operator Mode Workflow

```
1. View topology
   → list_devices()

2. Check device health
   → get_device_status("R1")

3. Find path
   → find_path("R1", "R5")

4. Diagnose latency
   → diagnose_latency("R1", "R5")
   (AI analyzes hop-by-hop, identifies bottlenecks)

5. Track trends (simulated only)
   → refresh_metrics() x5
   → predict_trends()
   (Shows if CPU will breach in 12 minutes)

6. Detect anomalies
   → refresh_metrics() x10
   → detect_anomalies()
   (Z-score spikes, rate shifts, volatility changes)

7. Root cause
   → analyze_root_cause("R2", "cpu")
   (Correlates with config changes, health events)
```

## Credits

Built with:
- [MCP SDK](https://github.com/anthropics/python-sdk) - Model Context Protocol
- [Netmiko](https://github.com/ktbyers/netmiko) - Multi-vendor SSH
- [TextFSM](https://github.com/google/textfsm) - Cisco output parsing


<img width="667" height="739" alt="Screenshot 2026-02-08 at 8 20 20 PM" src="https://github.com/user-attachments/assets/d6c4a4d5-0057-4779-ad73-17d8f04a27d6" />

<img width="559" height="626" alt="Screenshot 2026-02-08 at 8 23 10 PM" src="https://github.com/user-attachments/assets/3242478c-4f57-4d74-aea0-4706e2c4b62d" />
