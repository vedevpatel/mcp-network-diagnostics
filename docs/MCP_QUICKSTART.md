# MCP Quickstart

Get the network diagnostics MCP server running with Claude Desktop in under 5 minutes.

## 1. Clone and Install

```bash
git clone https://github.com/vedevpatel/mcp-network-diagnostics.git
cd mcp-network-diagnostics
uv sync
```

## 2. Add to Claude Desktop

Edit your Claude Desktop config:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

### Consumer Mode (Recommended Start)

No device credentials needed — diagnoses your own network:

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

Replace `/path/to/uv` with the output of `which uv`, and `/path/to/mcp-network-diagnostics` with the absolute path to the cloned repo.

### Simulated Mode (Testing Device Tools)

Includes a fake 10-router topology for testing operator tools without real devices:

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

## 3. Restart Claude Desktop

Quit and reopen Claude Desktop to load the new server.

## 4. Try It Out

Ask Claude:

> "Check my internet connection"

Claude will call `check_my_connection()` and show your WiFi signal, gateway latency, DNS timing, and internet connectivity.

### More Examples

| What to Ask | Tool Called |
|-------------|-------------|
| "Why is my Zoom laggy?" | `why_is_it_slow("zoom.us")` |
| "Trace the route to Google DNS" | `trace_path("8.8.8.8")` |
| "What devices are on my network?" | `scan_local_network()` |
| "Start tracking my connection baseline" | `record_baseline()` |
| "Is my connection worse than normal?" | `compare_to_baseline()` |

With simulated mode, also try:

| What to Ask | Tool Called |
|-------------|-------------|
| "Show me all network devices" | `list_devices()` |
| "What's the status of router R1?" | `get_device_status("R1")` |
| "Diagnose latency between R1 and R5" | `diagnose_latency("R1", "R5")` |

## Transports

The MCP server supports two transports:

| Transport | Use Case | Command |
|-----------|----------|---------|
| **stdio** (default) | Claude Desktop, local MCP clients | `mcp-network` |
| **streamable-http** | Remote API access, web integrations | `mcp-network --transport streamable-http --port 8000` |

For HTTP transport details, see the [README HTTP MCP Deployment section](../README.md#http-mcp-deployment) or the `/developer` page on the web dashboard.

## Next Steps

- **Web Dashboard**: Run `uv run python -m mcp_network.dashboard` and open http://localhost:8080
- **Real Devices**: See [Operator Mode - SSH](../README.md#operator-mode---ssh-devnet-sandboxes) for connecting to Cisco devices
- **Continuous Monitoring**: Use `set_intent("Alert me if latency exceeds 100ms")` to start the monitoring agent
- **Consumer Guide**: See [CONSUMER_MODE.md](../CONSUMER_MODE.md) for the full consumer feature guide
