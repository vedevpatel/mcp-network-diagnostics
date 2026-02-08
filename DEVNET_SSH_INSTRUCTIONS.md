# SSH Collector & DevNet Sandbox Integration Instructions

This document describes how to enhance the SSH collector with P2a robust data collection features and integrate with Cisco DevNet sandboxes for real-world testing.

## P2a: Robust Data Collection for SSH Collector

The simulated collector already tracks health and config changes. For the SSH collector, implement the following enhancements:

### 1. Retry Logic with Exponential Backoff

Add retry logic to `src/mcp_network/collectors/ssh.py`:

```python
import time
from typing import Optional

class SSHCollector:
    def __init__(self, topology_file: str, max_retries: int = 3, backoff_factor: float = 2.0):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        # ... existing init code ...

    def _collect_device_with_retry(self, device_id: str) -> Optional[Device]:
        """Collect device data with retry logic."""
        from mcp_network.collectors.health import get_health_tracker
        health_tracker = get_health_tracker()

        for attempt in range(self.max_retries):
            try:
                device = self._collect_device(device_id)
                health_tracker.record_success(device_id)
                return device
            except Exception as e:
                if attempt < self.max_retries - 1:
                    wait_time = self.backoff_factor ** attempt
                    time.sleep(wait_time)
                else:
                    # Final failure
                    health_tracker.record_failure(device_id, str(e))
                    return None
        return None
```

### 2. Partial Collection Support

Modify the collection loop to continue even if some devices fail:

```python
def collect_topology(self) -> dict[str, Device]:
    """Collect from all devices, returning partial results on failures."""
    devices = {}

    for device_id in self.topology_devices:
        device = self._collect_device_with_retry(device_id)
        if device:
            devices[device_id] = device
        else:
            # Log but continue
            print(f"Warning: Failed to collect {device_id}, continuing with partial data")

    return devices
```

### 3. Config Snapshot Integration

Add config collection to SSH collector:

```python
def collect_configs(self):
    """Collect and track configuration snapshots."""
    from mcp_network.config import get_config_tracker
    config_tracker = get_config_tracker()

    for device_id in self.topology_devices:
        try:
            config_text = self.run_command(device_id, "show running-config")
            config_tracker.add_snapshot(device_id, config_text)
        except Exception as e:
            print(f"Warning: Failed to collect config for {device_id}: {e}")
```

Call this method periodically (e.g., every 5 minutes) or on-demand via a new MCP tool.

### 4. Staleness Detection

The health tracker already computes staleness based on `last_success_time`. Ensure the SSH collector calls `refresh()` or updates timestamps regularly.

## DevNet Sandbox Integration

### Available Sandboxes

1. **IOS XE on Catalyst 8000V** (Always-On)
   - Host: `sandbox-iosxe-latest-1.cisco.com`
   - Port: 22
   - Username: `admin`
   - Password: `C1sco12345`
   - Type: IOS XE

2. **Nexus 9000v (NX-OS)** (Reservation Required)
   - Reserve at: https://devnetsandbox.cisco.com/
   - Search for "Nexus 9000"
   - Type: NX-OS

### Example Topology File for DevNet

Create `examples/devnet_topology.yaml`:

```yaml
devices:
  cat8kv-1:
    hostname: sandbox-iosxe-latest-1.cisco.com
    port: 22
    username: admin
    password: C1sco12345
    device_type: cisco_ios  # For netmiko

thresholds:
  cpu: 80.0
  utilization: 75.0
  errors: 100
  anomaly:
    z_score_threshold: 2.0
    rate_shift_threshold: 3.0
    volatility_ratio_threshold: 3.0
    min_samples: 5

local_device: cat8kv-1
```

### Testing P2 Features on DevNet

#### Test Collection Health

```bash
# Start server with SSH collector
mcp-network --collector ssh --topology examples/devnet_topology.yaml

# In Claude Desktop, invoke:
get_collection_health()

# Expected: Should show reachability, staleness, quality score
```

#### Test Config Tracking

```bash
# Make a config change on the sandbox device:
ssh admin@sandbox-iosxe-latest-1.cisco.com
configure terminal
logging buffered 10000
end
write memory

# In Claude Desktop:
get_config_history("cat8kv-1")
# Should show the config change

compare_configs("cat8kv-1", "<time_before>", "<time_after>")
# Should show diff with "logging buffered 10000"
```

#### Test Causal Analysis

For causal analysis to work meaningfully, you need multiple interconnected devices. Options:

1. **Reserve a Multi-Device Sandbox**: Reserve a full topology sandbox from DevNet (e.g., "Multi-IOS Test Network")

2. **Use Multiple Always-On Sandboxes**: Connect to both IOS XE and NX-OS sandboxes simultaneously

3. **Simulate Some Devices**: Mix real SSH devices with simulated devices in your topology

Example mixed topology:

```yaml
devices:
  # Real device
  cat8kv-1:
    hostname: sandbox-iosxe-latest-1.cisco.com
    port: 22
    username: admin
    password: C1sco12345
    device_type: cisco_ios

  # Simulated devices for topology
  R2:
    simulated: true
  R3:
    simulated: true

links:
  - src_device: cat8kv-1
    src_interface: GigabitEthernet1
    dst_device: R2
    dst_interface: Gi0/0
    latency_ms: 2.5
  - src_device: R2
    src_interface: Gi0/1
    dst_device: R3
    dst_interface: Gi0/0
    latency_ms: 3.0
```

### SSH Collector Implementation Checklist

- [ ] Add retry logic with exponential backoff
- [ ] Implement partial collection (continue on device failures)
- [ ] Integrate health tracking (record_success/record_failure)
- [ ] Add config snapshot collection
- [ ] Call config_tracker.add_snapshot() periodically
- [ ] Add `collect_configs()` MCP tool
- [ ] Test with DevNet sandbox
- [ ] Handle connection timeouts gracefully
- [ ] Log failures without crashing
- [ ] Update staleness timestamps on each successful collection

### Prometheus Collector

For the Prometheus collector, implement similar patterns:

1. **Health Tracking**: Record success/failure for each scrape
2. **Staleness**: Use Prometheus timestamp metadata to detect stale metrics
3. **Config Tracking**: Not applicable (Prometheus doesn't have device configs)
4. **Partial Collection**: Continue scraping even if some targets are down

### Testing Strategy

1. **Unit Tests**: Use mocked SSH connections
2. **Integration Tests**: Use DevNet always-on sandboxes in CI/CD
3. **Manual Testing**: Reserve full topology sandboxes for end-to-end validation

### Security Notes

- Store credentials in environment variables or secure vaults (not YAML files)
- Use SSH keys instead of passwords where possible
- Implement read-only access (show commands only)
- Never commit credentials to git

### Performance Considerations

- Collection interval: 60-120 seconds recommended
- Config snapshots: Every 5-10 minutes (they change infrequently)
- Parallel collection: Use threading or asyncio for multiple devices
- Timeout: 30 seconds per device recommended

## Next Steps

1. Implement retry logic in `src/mcp_network/collectors/ssh.py`
2. Add health tracking integration
3. Add config collection support
4. Test with DevNet sandbox
5. Add integration tests using DevNet credentials from environment
6. Document in main README.md
