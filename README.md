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

## Current Limitations
- Read-only (no device configuration changes)
- Static topology (define devices/links in YAML)
- node_exporter metrics only (SNMP planned for future)
- Tested with Claude; other LLMs may vary
