# Consumer Mode: AI Network Diagnostics for Everyone

## The Vision

**Two modes, one codebase, same intelligence:**

| Mode | Audience | Data Source | Example Use Case |
|------|----------|-------------|------------------|
| **Operator Mode** | Network engineers | SSH, SNMP, vManage API | "Diagnose latency in datacenter fabric" |
| **Consumer Mode** | Everyone | Ping, traceroute, DNS | "Why is my Zoom call laggy?" |

Same diagnostic engine. Different data collection. Different confidence levels.

---

## What Consumer Mode Does

Diagnoses network issues **from your perspective** using standard tools — no device credentials required.

### You Can Diagnose:

| Problem | How It's Detected |
|---------|-------------------|
| Bad WiFi signal | High ping to gateway, low signal strength |
| Router overloaded | Gateway latency spikes, many local devices |
| ISP has issues | First external hop shows high latency/loss |
| Destination is slow | Last hops slow, earlier hops fine |
| DNS is slow | High DNS resolution time vs ping |
| Packet loss somewhere | Traceroute shows loss at specific hop |
| Peering congestion | Mid-path hop (ISP boundary) shows latency |

###  What You Get:

✅ **Bottleneck Identification**: "The issue is at hop 4, inside Comcast's network"
✅ **Confidence Scores**: "82% confidence this is an ISP issue"
✅ **Actionable Suggestions**: "Try mobile hotspot as workaround"
✅ **Human-Readable Explanations**: No network engineering degree required

---

## New MCP Tools

### `why_is_it_slow(destination)`

Comprehensive diagnosis of slowness to any destination.

**Example:**
```python
# User asks: "Why is my Zoom call laggy?"
await why_is_it_slow("zoom.us")
```

**Returns:**
```json
{
  "destination": "zoom.us",
  "diagnosis": {
    "bottleneck": "isp_internal",
    "confidence": 0.82,
    "summary": "The issue is inside your ISP's network"
  },
  "issues": [
    "ISP network slow at hop 4 (68.86.103.126)"
  ],
  "suggestions": [
    "This issue is inside your ISP's network — outside your control",
    "Check downdetector.com for reported ISP outages",
    "Try mobile hotspot as temporary workaround"
  ],
  "path_analysis": {
    "wifi": {"status": "good", "signal_dbm": -52},
    "local_network": {"status": "healthy", "latency_ms": 2.3},
    "dns": {"resolution_ms": 15.2},
    "total_latency_ms": 174
  }
}
```

---

### `check_my_connection()`

Quick health check of your internet connection.

**Tests:**
- WiFi signal (if wireless)
- Gateway (local router)
- DNS resolution
- External connectivity

**Returns:**
```json
{
  "overall_status": "healthy",
  "issues": [],
  "layers": {
    "wifi": {
      "available": true,
      "ssid": "MyNetwork",
      "signal_strength_dbm": -45,
      "quality": "excellent"
    },
    "local_network": {
      "gateway_ip": "192.168.1.1",
      "latency_ms": 1.8,
      "loss_pct": 0.0,
      "status": "healthy"
    },
    "dns": {
      "google_ms": 12.3,
      "cloudflare_ms": 8.9
    },
    "internet": {
      "latency_to_8888_ms": 18.4,
      "packet_loss_pct": 0.0
    }
  }
}
```

---

### `trace_path(destination)`

Show network path with latency per hop, identify bottleneck.

**Example:**
```python
await trace_path("netflix.com")
```

**Returns:**
```json
{
  "destination": "netflix.com",
  "hops": [
    {"number": 1, "ip": "192.168.1.1", "latency_ms": 2.1, "is_bottleneck": false},
    {"number": 2, "ip": "10.0.0.1", "latency_ms": 8.3, "is_bottleneck": false},
    {"number": 3, "ip": "68.86.103.1", "latency_ms": 15.7, "is_bottleneck": false},
    {"number": 4, "ip": "68.86.103.126", "latency_ms": 145.2, "is_bottleneck": true},
    ...
  ],
  "bottleneck": {
    "hop_number": 4,
    "ip": "68.86.103.126",
    "latency_jump_ms": 129.5,
    "segment": "isp",
    "explanation": "The bottleneck is inside your ISP's network"
  }
}
```

---

### `scan_local_network()`

List devices on your local network (LAN) from the system ARP table.

**Example:**
```python
await scan_local_network()
```

**Returns:**
```json
{
  "devices": [
    {"ip": "192.168.1.1", "mac": "aa:bb:cc:dd:ee:ff", "hostname": "router.local"},
    {"ip": "192.168.1.5", "mac": "11:22:33:44:55:66", "hostname": null}
  ],
  "count": 2,
  "note": "Devices are from the system ARP cache (recent traffic only)."
}
```

Only hosts your machine has recently communicated with appear (no broadcast ping). Works on macOS, Linux, and Windows.

---

## How It Works

### EdgeCollector

Runs standard network tools from your computer:

```python
from mcp_network.collectors.edge import EdgeCollector

collector = EdgeCollector()

# Full diagnostic probe
probe = await collector.probe_destination("google.com")

# Returns:
# - Gateway ping results
# - DNS resolution timing
# - Traceroute hop-by-hop
# - HTTP timing breakdown (if URL)
# - WiFi stats (platform-specific)
```

### Cross-Platform Support

- ✅ **macOS**: Full support (ping, traceroute, WiFi via Airport)
- ✅ **Linux**: Full support (ping, mtr/traceroute, WiFi via iw)
- ✅ **Windows**: Full support (ping, tracert, WiFi via netsh)

Uses platform-appropriate commands automatically.

### WiFi detection (SSID and signal) per OS

The dashboard and `check_my_connection()` show the **current machine’s** WiFi name (SSID) and signal when available. How it’s detected depends on the OS:

| OS      | Primary source              | Fallback(s) for SSID                    | Notes |
|---------|-----------------------------|-----------------------------------------|--------|
| **macOS** | `airport -I`                | `networksetup -getairportnetwork`, `ipconfig getsummary` | Uses full paths (`/usr/sbin/networksetup`, etc.) so it works under `uv` and restricted PATH. Wi‑Fi interface is discovered via `networksetup -listallhardwareports`. |
| **Linux** | `iw dev … link` / `iwconfig` | `nmcli -t -f active,ssid dev wifi`      | Needs `iw` or `iwconfig` for signal; SSID can come from `nmcli` if the primary tool doesn’t report it. |
| **Windows** | `netsh wlan show interfaces` | —                                       | No extra fallback; SSID and signal % are parsed from netsh. |

**Limitations**

- **Docker / containers**: The process runs inside the container, which usually has no WiFi interface. You’ll see “Network name unavailable” or “Not on WiFi”. Run the app on the host (e.g. your Mac) to see the real SSID and signal.
- **macOS Sequoia+**: `ipconfig getsummary` may show `<redacted>` for SSID unless verbose mode is enabled; `networksetup` is tried first.
- **No WiFi**: On wired-only or headless machines, WiFi stats are `null` and the UI shows “Not on WiFi” where applicable.

**How to verify on your machine**

- Run the dashboard on the same OS/machine where you want to see WiFi (e.g. `uv run python -m mcp_network.dashboard` on your Mac).
- Open the “My Connection” / Overview page; the WiFi card should show your SSID and signal when connected.
- Unit tests in `tests/test_edge_collector.py` (class `TestWifiDetectionPerOS`) mock subprocess output for macOS, Linux, and Windows to lock parsing behavior; run with `pytest tests/test_edge_collector.py::TestWifiDetectionPerOS -v`.

---

## Example User Interaction

**User to Claude:**
> "My video call keeps freezing. What's wrong with my internet?"

**Claude calls:** `why_is_it_slow("meet.google.com")`

**Claude responds:**
> Your video call issues are caused by WiFi signal strength. You're showing -72 dBm which is "fair" quality, and your ping to your router is spiking to 45ms when it should be under 5ms.
>
> Quick fixes:
> 1. Move closer to your WiFi router
> 2. Switch to the 5GHz network if you have it
> 3. Use an Ethernet cable if possible
>
> Your internet connection itself is fine (8ms to Google's servers), so the problem is definitely your WiFi signal.

---

## Use Cases

### Home Users
- "Why is Netflix buffering?"
- "Is my internet down or is it just me?"
- "Which device on my network is using all the bandwidth?"

### Remote Workers
- "Why is my VPN slow?"
- "Should I upgrade my internet plan?"
- "Is this a good time to join a video call?"

### Gamers
- "Why is my ping so high?"
- "Which server location is fastest?"
- "Is my ISP throttling me?"

### Tech Support
- "Walk me through testing my connection"
- "Is the issue on my end or theirs?"
- "What do I tell my ISP when I call them?"

---

## Implementation Status

### Phase 1: Core (Implemented ✅)
- [x] EdgeCollector with ping, DNS, traceroute
- [x] why_is_it_slow() tool
- [x] check_my_connection() tool
- [x] trace_path() tool
- [x] Cross-platform ping/traceroute parsing
- [x] Bottleneck identification algorithm
- [x] WiFi stats (macOS)
- [x] Tests (8 passing)

### Phase 2: Baseline & History (Implemented ✅)
- [x] Baseline storage (JSON file at ~/.mcp_network/edge_baseline.json)
- [x] record_baseline() tool - Record current state as baseline
- [x] compare_to_baseline() tool - Compare current vs historical
- [x] clear_baseline() tool - Reset baseline data
- [x] "Normally 45ms, currently 180ms — 4x slower" explanations
- [x] Anomaly detection on edge metrics (z-score based)
- [x] Automatic baseline persistence across sessions
- [x] Tests (19 passing)

### Phase 3: Polish (Implemented ✅)
- [x] WiFi stats for Linux (iw/iwconfig)
- [x] WiFi stats for Windows (netsh)
- [x] Speedtest integration (run_speedtest() tool)
- [x] Better Windows tracert parsing (handles timeouts, averages latency)
- [x] Local network scan (scan_local_network() — ARP table, macOS/Linux/Windows)
- [ ] AS lookup for hop ownership (Future: identify ISPs by ASN)

---

## Key Differentiators

### vs. Fast.com / Speedtest.net
- **They:** Measure speed to their servers
- **Us:** Identify *where* the slowdown is and *why*

### vs. PingPlotter
- **They:** Network visualization tool for power users
- **Us:** AI agent that explains in plain English

### vs. ISP Support
- **They:** "Have you tried turning it off and on again?"
- **Us:** "The issue is at hop 4 in Comcast's Chicago peering point"

---

## Testing

```bash
# Quick test - baseline storage
python -m pytest tests/test_baseline.py::TestBaselineStorage::test_compare_to_baseline_anomalous -v

# All edge tests (slower - real network operations)
python -m pytest tests/test_edge_collector.py tests/test_baseline.py -v

# Manual test - establish baseline
python -c "
import asyncio
from mcp_network.tools import record_baseline, compare_to_baseline

async def test():
    # Record baseline 5 times
    for i in range(5):
        print(f'Recording baseline {i+1}/5...')
        result = await record_baseline()
        print(result)

    # Compare current to baseline
    print('\\nComparing to baseline:')
    result = await compare_to_baseline()
    print(result)

asyncio.run(test())
"
```

---

## Usage Example: Baseline Workflow

```python
# 1. Check current connection
await check_my_connection()

# 2. If healthy, record as baseline (do this 5-10 times over a few days)
await record_baseline()

# 3. Later, when experiencing issues:
result = await compare_to_baseline()

# Shows output like:
# {
#   "overall_status": "warning",
#   "anomalies": [
#     {
#       "metric": "gateway_latency_ms",
#       "severity": "critical",
#       "explanation": "Gateway latency: 45.2ms (normally 8.3ms, 5.4x worse)"
#     }
#   ]
# }
```

## Next Steps

1. **Try it yourself**: Run `check_my_connection()` or `why_is_it_slow("google.com")`
2. **Build your baseline**: Run `record_baseline()` 5-10 times when connection is good
3. **Monitor over time**: Use `compare_to_baseline()` to detect degradation
4. **Polish platform support**: Complete WiFi stats for all OSes (Phase 3)
5. **Marketing**: "AI network diagnostics for everyone"

---

## The Bigger Picture

**Operator Mode** → Enterprise sales, Cisco partnerships, network engineers
**Consumer Mode** → Community growth, consumer apps, everyone

Same codebase. Same intelligence. Different audiences. Both valuable.

Consumer mode drives GitHub stars and community engagement.
Operator mode drives enterprise revenue and technical credibility.

**Win-win.**
