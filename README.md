# MCP Network Diagnostics
Diagnose network latency issues using AI.

## What this does
This MCP server lets AI agents inspect network topology and metrics to explain
why latency is high between two devices.

It focuses on read-only, deterministic diagnostics, not automation.



## Data Sources

### Simulated Collector (Default)
Generates a fake 10-router mesh topology for testing and demos. No setup required.

```bash
mcp-network --collector simulated
```

### Prometheus Collector
Query real metrics from homelab or production network.

#### Prerequisites
1. Prometheus server (default: http://localhost:9090)
2. node_exporter running on network devices
3. Topology configuration file

#### Start with Docker

```bash
docker run -d -p 9090:9090 --name prometheus prom/prometheus

docker run -d -p 9100:9100 --name node-exporter prom/node-exporter
```

#### Configure Network Topology

Create or edit `network_topology.yaml`:

```yaml
devices:
  - id: router-1
    type: router
    prometheus_labels:
      instance: "192.168.1.1:9100"
      job: "node_exporter"
    interfaces:
      - name: eth0
        prometheus_name: eth0
        link_speed_mbps: 1000

  - id: router-2
    type: router
    prometheus_labels:
      instance: "192.168.1.2:9100"
      job: "node_exporter"
    interfaces:
      - name: eth0
        prometheus_name: eth0
        link_speed_mbps: 1000

links:
  - src_device: router-1
    src_interface: eth0
    dst_device: router-2
    dst_interface: eth0
    default_latency_ms: 2.0
```

#### Run with Prometheus

```bash
mcp-network --collector prometheus \
  --prometheus-url http://localhost:9090 \
  --topology-file network_topology.yaml
```

#### Environment Variables

```bash
export MCP_NETWORK_COLLECTOR=prometheus
export MCP_NETWORK_PROMETHEUS_URL=http://localhost:9090
export MCP_NETWORK_TOPOLOGY_FILE=network_topology.yaml
export MCP_NETWORK_CACHE_TTL=30

mcp-network
```

#### Claude Desktop Integration with Prometheus

Update `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "network-diagnostics": {
      "command": "/Users/vedpatel/.local/bin/uv",
      "args": [
        "--directory",
        "/path/to/mcp-network-diagnostics",
        "run",
        "mcp-network",
        "--collector",
        "prometheus",
        "--prometheus-url",
        "http://localhost:9090",
        "--topology-file",
        "/path/to/network_topology.yaml"
      ]
    }
  }
}
```

### SSH Collector (Cisco DevNet or your own routers)
Connect to real Cisco routers via SSH. Supports IOS-XR, IOS-XE, or a
mix of both in a single topology file.

#### Quickstart with DevNet Always-On sandboxes

DevNet provides free, always-on Cisco routers — no VPN or lab setup needed.
Get your credentials from [developer.cisco.com](https://developer.cisco.com).

```bash
export DEVNET_IOSXR_USERNAME=<your username>
export DEVNET_IOSXR_PASSWORD=<your password>
export DEVNET_IOSXE_USERNAME=<your username>
export DEVNET_IOSXE_PASSWORD=<your password>

mcp-network --collector ssh --topology-file devnet_topology.yaml
```

`devnet_topology.yaml` connects to both sandboxes and declares a synthetic
link between them so that path-finding and latency diagnosis work across
the two devices.

#### Claude Desktop integration

Update `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "network-diagnostics": {
      "command": "/Users/vedpatel/.local/bin/uv",
      "args": [
        "--directory",
        "/path/to/mcp-network-diagnostics",
        "run",
        "mcp-network",
        "--collector",
        "ssh",
        "--topology-file",
        "/path/to/devnet_topology.yaml"
      ],
      "env": {
        "DEVNET_IOSXR_USERNAME": "your_username",
        "DEVNET_IOSXR_PASSWORD": "your_password",
        "DEVNET_IOSXE_USERNAME": "your_username",
        "DEVNET_IOSXE_PASSWORD": "your_password"
      }
    }
  }
}
```

Then ask Claude things like:
- "What's the status of devnet-iosxr-1?"
- "Diagnose latency from devnet-iosxr-1 to devnet-iosxe-1"

#### Using your own routers

Copy `devnet_topology.yaml` to `mynetwork_topology.local.yaml` (the
`.local.yaml` suffix is gitignored), edit in your device IPs and
`${VAR}` placeholders or literal values, and point the server at it:

```bash
mcp-network --collector ssh --topology-file mynetwork_topology.local.yaml
```

Set `device_type: iosxr` or `device_type: iosxe` on each device so the
collector picks the right show commands and parsers.

---

## Topology file format

All topology files are YAML with the same structure:

```yaml
devices:
  - id: my-router          # unique ID used in tool calls
    type: router            # router or switch
    device_type: iosxr      # iosxr or iosxe (ssh collector only)
    host: 192.168.1.1
    username: ${MY_USER}    # literal value or ${ENV_VAR} placeholder
    password: ${MY_PASS}
    port: 22

links:
  - src_device: my-router
    src_interface: GigabitEthernet0/0/0/0
    dst_device: other-router
    dst_interface: GigabitEthernet1
    default_latency_ms: 2.0
```

**`${VAR_NAME}` placeholders** are replaced with the value of the
environment variable `VAR_NAME` at startup. The server exits with a
clear error if any referenced variable is not set.

**`.local.yaml` convention** — files matching `*_topology.local.yaml`
are gitignored. Copy an example topology to a `.local.yaml` file when
you want to fill in real credentials without committing them.

---

## Current Limitations
- Read-only (no device configuration changes)
- Static topology (define devices/links in YAML)
- DevNet sandbox credentials rotate periodically; if SSH fails, grab fresh credentials from developer.cisco.com
- Tested with Claude; other LLMs may vary
