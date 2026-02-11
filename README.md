# MCP Network Diagnostics
 
[![CI](https://github.com/vedevpatel/mcp-network-diagnostics/actions/workflows/ci.yml/badge.svg)](https://github.com/vedevpatel/mcp-network-diagnostics/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/mcp-network.svg)](https://pypi.org/project/mcp-network/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-network.svg)](https://pypi.org/project/mcp-network/)
[![License](https://img.shields.io/github/license/vedevpatel/mcp-network-diagnostics.svg)](https://github.com/vedevpatel/mcp-network-diagnostics/blob/main/LICENSE)

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
Diagnose your home/office network without device access. See **[CONSUMER_MODE.md](CONSUMER_MODE.md)** for the full consumer guide (tools, baseline workflow, use cases).
- **Web dashboard** – Browser UI with "My Connection" overview, consumer tools, guest sessions, and per-identity baselines
- Gateway health checks
- DNS resolution timing
- Traceroute with hop analysis
- WiFi signal quality (macOS/Linux/Windows)
- Baseline tracking with anomaly detection (per-identity when using the dashboard)
- Provider context (BGP/AS lookup, outage correlation)
- Continuous monitoring agent with intent system
- Speedtest integration

## Quick Start

### Installation

```bash
# Install from source
git clone https://github.com/vedevpatel/mcp-network-diagnostics.git
cd mcp-network-diagnostics
uv sync
```

### Quick start (Consumer)

One command to run the dashboard, then open the app in your browser—no API key or sign-in required:

```bash
uv run python -m mcp_network.dashboard
# Open http://localhost:8080
```

Use the site as a **guest** (session is identified by a signed cookie; baselines and data are scoped per identity). From the Overview you get a live "My Connection" view (gateway, DNS, internet latency). From **Tools** you can run "Check my connection", "Trace path", "Why is it slow?", and baseline record/compare.

To use the same diagnostics from Claude (or any MCP client), point your [Claude Desktop config](#consumer-mode-no-setup-required) at this repo and run `check_my_connection()` or `why_is_it_slow("zoom.us")` via MCP.

For the full consumer guide—all tools, baseline workflow, and use cases—see **[CONSUMER_MODE.md](CONSUMER_MODE.md)**.

### Web Dashboard (Consumer UI)

Run the dashboard for a browser-based "check my connection" experience—no MCP or API key required:

```bash
uv run python -m mcp_network.dashboard
# Open http://localhost:8080
```

- **Overview** – "My Connection" live status (gateway, DNS, latency).
- **Tools** – Consumer tools (Check my connection, Trace path, Why is it slow?, Record/compare baseline, etc.) plus operator and agent tools when configured.
- **Guest session** – A signed cookie identifies your session; baselines and data are scoped per identity. Header shows "Using as guest" (optional "Sign in" for future use).
- **Rate limits** – Per-guest limit (default 60 requests/min). Set `CONSUMER_RATE_LIMIT_PER_MINUTE` to override.
- **Optional auth** – Set `MCP_NETWORK_DASHBOARD_REQUIRE_AUTH=1` to require an API key for Tools and Settings.

With Docker: `docker compose up -d` then open http://localhost:8080.

### MCP Integration (Claude Desktop)

Add the MCP server to Claude Desktop by editing `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows).

#### Consumer Mode (No Setup Required)

Diagnose your own network — no credentials, no config files:

```json
{
  "mcpServers": {
    "network-diagnostics": {
      "command": "/path/to/uv",
      "args": ["--directory", "/path/to/mcp-network-diagnostics", "run", "mcp-network"]
    }
  }
}
```

#### Operator Mode (Simulated — Testing/Demos)

Try device diagnostics with a fake 10-router topology:

```json
{
  "mcpServers": {
    "network-diagnostics": {
      "command": "/path/to/uv",
      "args": ["--directory", "/path/to/mcp-network-diagnostics", "run", "mcp-network", "--collector", "simulated"]
    }
  }
}
```

**Restart Claude Desktop** after editing the config.

### Key MCP Tools

| Tool | Use Case |
|------|----------|
| `check_my_connection()` | Quick health check — WiFi, gateway, DNS, internet latency |
| `why_is_it_slow("zoom.us")` | Diagnose slow connections — pinpoints bottleneck location |
| `trace_path("8.8.8.8")` | Traceroute with AS/provider info per hop |
| `scan_local_network()` | List devices on your LAN (from ARP table) |
| `record_baseline()` / `compare_to_baseline()` | Track normal behavior, detect anomalies |
| `set_intent("Zoom should stay under 100ms")` | Continuous monitoring with natural language goals |

**Operator-only tools** (requires `--collector simulated` or SSH/Prometheus):
| Tool | Use Case |
|------|----------|
| `list_devices()` / `get_device_status("R1")` | View topology and device health |
| `diagnose_latency("R1", "R5")` | AI-powered hop-by-hop latency diagnosis |
| `predict_trends()` | Forecast metric breaches (needs 5+ samples) |
| `detect_anomalies()` | Statistical anomaly detection across devices |

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
| `scan_local_network()` | List devices on your LAN (from ARP table) |

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

## Transports

The MCP server supports two transports:

| Transport | Use Case | How to Connect |
|-----------|----------|----------------|
| **stdio** (default) | Claude Desktop, local MCP clients | Add to `claude_desktop_config.json` |
| **streamable-http** | Remote API access, web integrations, multi-client | HTTP endpoint at `http://host:port/mcp` |

### stdio Transport

Default for Claude Desktop. The MCP client spawns the server as a subprocess and communicates over stdin/stdout.

```bash
# Run directly (for testing)
mcp-network --collector simulated

# Claude Desktop config points to the command
```

### HTTP Transport

For remote access or when multiple clients need to connect to the same server.

```bash
mcp-network --transport streamable-http --port 8000 --path /mcp
# Endpoint: http://localhost:8000/mcp
```

Clients connect via HTTP POST to the `/mcp` endpoint using the MCP JSON-RPC protocol.

## HTTP MCP Deployment

For production HTTP MCP deployments:

### Basic Usage

```bash
# Start HTTP MCP server (no auth)
uv run mcp-network --transport streamable-http --port 8000 --path /mcp

# With authentication required
uv run mcp-network --transport streamable-http --port 8000 --require-auth
```

### Authentication & API Keys

When `--require-auth` is set, clients must provide an API key:

```bash
curl -X POST http://localhost:8000/mcp \
  -H "Authorization: Bearer mcp_YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Create API keys via:
- The `create_api_key` MCP tool (superuser role)
- The dashboard Settings page (when using API keys file)
- Directly in `~/.mcp_network/api_keys.json`

**Roles**: `consumer` (edge tools only) → `operator` (+ device access) → `admin` (+ agent control) → `superuser` (full access). See [SECURITY.md](SECURITY.md) for details.

### Rate Limiting

- **Per-key limits**: Based on role (consumer: 60/min, operator: 120/min, admin: 300/min)
- **Global limit**: 1000 req/min total (override with `MCP_NETWORK_GLOBAL_RPM` env var)
- Exceeded limits return HTTP 429 with `Retry-After` header

### Docker Deployment

```bash
# Build and run
docker compose up -d

# Access dashboard at http://localhost:8080
```

For HTTP MCP behind a reverse proxy:

```yaml
# docker-compose.override.yml
services:
  mcp-http:
    build: .
    command: ["uv", "run", "mcp-network", "--transport", "streamable-http", "--port", "8000", "--require-auth"]
    ports:
      - "8000:8000"
    environment:
      - MCP_NETWORK_SESSION_SECRET=${SESSION_SECRET}
    volumes:
      - ./api_keys.json:/root/.mcp_network/api_keys.json:ro
```

Put nginx or Caddy in front for TLS termination:

```nginx
# nginx.conf snippet
location /mcp {
    proxy_pass http://mcp-http:8000/mcp;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

### Security Considerations

When deploying HTTP MCP:

- **Always use TLS** in production (terminate at reverse proxy)
- **Set a strong session secret**: `export MCP_NETWORK_SESSION_SECRET=$(openssl rand -hex 32)`
- **Configure CORS**: `MCP_NETWORK_CORS_ORIGINS=https://your-app.com` (defaults to same-origin only)
- **SSRF protection**: Consumer tools validate destinations to prevent internal network scanning
- **Command injection**: SSH collector validates commands are read-only (`show`, `display`, etc.)
- **Rate limiting**: Enabled by default; tune via env vars

See [SECURITY.md](SECURITY.md) for the full threat model and security architecture.

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

### Quick Smoke Tests

While the dashboard is running (`uv run python -m mcp_network.dashboard`):

```bash
# Test all dashboard endpoints, rate limiting, session handling
./test_dashboard_curl.sh

# Test with lower rate limit for faster rate-limit verification
CONSUMER_RATE_LIMIT_PER_MINUTE=10 ./test_dashboard_curl.sh
```

### Developer Resources

- **[docs/MCP_QUICKSTART.md](docs/MCP_QUICKSTART.md)** — 5-minute guide to get Claude Desktop connected
- **[examples/mcp_client_example.py](examples/mcp_client_example.py)** — Programmatic MCP client usage
- **[examples/http_mcp_examples.sh](examples/http_mcp_examples.sh)** — curl examples for HTTP MCP API

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
├── dashboard/           # Web UI (consumer + operator views)
│   ├── app.py           # FastAPI app, session middleware
│   ├── session.py       # Guest session (signed cookie)
│   ├── consumer_limits.py  # Per-identity rate limits
│   ├── routes/          # Overview, tools, devices, incidents, etc.
│   └── templates/       # Jinja2 HTML
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
