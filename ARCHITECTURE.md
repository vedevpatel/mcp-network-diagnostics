# Architecture Overview

## The Three Leaps

This project evolved through three strategic leaps, transforming from reactive diagnostics to autonomous intelligence.

### Leap 1: External Context Integration

**Goal:** Enrich diagnostics with external knowledge about the internet.

**What was built:**
- `BGPContext` - AS/BGP lookup via Team Cymru DNS (free, no auth)
- `OutageContext` - Cloud provider status monitoring (Cloudflare, AWS, Google, etc.)
- Traceroute enrichment with AS numbers and provider info
- Context notes in diagnostic output

**Impact:** Diagnostics now say "Latency spike at AS15169 (Google)" instead of just "Hop 5 slow".

**Files:**
- `src/mcp_network/context/bgp.py`
- `src/mcp_network/context/outages.py`

---

### Leap 2: Continuous Monitoring Agent

**Goal:** Transform from reactive (user asks → diagnose) to proactive (always watching → auto-alerts).

**What was built:**
- `NetworkAgent` - Background loop monitoring network state
- `IntentParser` - Converts natural language goals to structured intents
- 7 new MCP tools for agent control
- Automatic baseline tracking and updates
- Alert cooldown and rate limiting
- Incident logging with severity scoring

**Impact:** Users say "Zoom calls should never lag" and the agent handles the rest.

**Files:**
- `src/mcp_network/agent/core.py`
- `src/mcp_network/agent/intents.py`

**Tools:**
- `start_agent()` / `stop_agent()`
- `set_intent()` / `list_intents()` / `remove_intent()`
- `get_incidents()` / `agent_status()`

---

### Leap 3: Autonomous Planning & Execution

**Goal:** Let users define goals in plain English, system figures out *how* to implement them.

**What was built:**
- `IntentPlanner` - Generates action plans from natural language
- `ActionExecutor` - Executes actions with safety guardrails
- `AutonomousAgent` - Combines planning + execution
- Goal classification (threshold, baseline, diagnostic, quality)
- Multi-action plans with triggers and guardrails
- Confidence scoring for plans

**Impact:** System autonomously decides monitoring strategy, thresholds, actions, and safety limits.

**Files:**
- `src/mcp_network/agent/planner.py`
- `src/mcp_network/agent/executor.py`

**Tools:**
- `plan_goal(goal)` - Preview action plan
- `execute_plan(intent_id)` - Activate the plan
- `get_guardrail_status()` - View safety state

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   MCP Server (stdio)                     │
│                                                          │
│  ┌────────────────────────────────────────────────────┐ │
│  │              Natural Language Layer                │ │
│  │  User: "Keep Zoom responsive during work hours"   │ │
│  │         ↓                                          │ │
│  │  IntentPlanner: Generate action plan              │ │
│  │         ↓                                          │ │
│  │  ActionExecutor: Apply guardrails & execute       │ │
│  └────────────────────────────────────────────────────┘ │
│                        ↓                                 │
│  ┌────────────────────────────────────────────────────┐ │
│  │              Intelligence Layer                    │ │
│  │  • Path finding       • Trend prediction          │ │
│  │  • Anomaly detection  • Root cause analysis       │ │
│  │  • Intent parsing     • Context enrichment        │ │
│  └────────────────────────────────────────────────────┘ │
│                        ↓                                 │
│  ┌────────────────────────────────────────────────────┐ │
│  │              Monitoring Layer                      │ │
│  │  NetworkAgent (continuous loop):                  │ │
│  │    1. Collect state                               │ │
│  │    2. Check intents                               │ │
│  │    3. Diagnose violations                         │ │
│  │    4. Execute actions                             │ │
│  │    5. Update baselines                            │ │
│  └────────────────────────────────────────────────────┘ │
│                        ↓                                 │
│  ┌──────────────┬─────────────────────────────────────┐ │
│  │ Operator     │         Consumer Mode               │ │
│  │ Mode         │                                     │ │
│  │              │  • EdgeCollector (ping/trace/DNS)  │ │
│  │ • SSH        │  • BaselineStorage (ring buffers)  │ │
│  │ • Prometheus │  • BGPContext (AS lookup)          │ │
│  │ • Simulated  │  • OutageContext (provider status) │ │
│  └──────────────┴─────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

---

## Data Flow: Natural Language → Action

**Example:** User says `"Keep Zoom responsive during work hours"`

### 1. Planning Phase (`plan_goal`)

```python
goal = "Keep Zoom responsive during work hours"
           ↓
IntentPlanner.plan(goal):
    - Classify: continuous_quality_goal
    - Extract target: "zoom.us"
    - Extract metrics: ["latency", "loss"]
    - Generate actions:
        [
            Action(type="monitor", target="zoom.us", metric="latency", threshold=100, comparison="<"),
            Action(type="monitor", target="zoom.us", metric="loss", threshold=1.0, comparison="<"),
            Action(type="record", params={"continuous": True}),
            Action(type="diagnose", params={"on": "violation", "priority": "high"}),
            Action(type="alert", params={"on": "violation"}),
        ]
    - Add guardrails:
        ["alert_cooldown_300s", "max_alerts_per_hour_10", "auto_disable_on_persistent_failure"]
    - Confidence: 0.9
           ↓
ActionPlan returned to user for review
```

### 2. Execution Phase (`execute_plan`)

```python
ActionExecutor checks guardrails:
    - Alert cooldown: ✓ (no recent alerts)
    - Rate limits: ✓ (0/10 alerts this hour)
    - Failures: ✓ (0 consecutive failures)
           ↓
Convert plan → Intent → Add to NetworkAgent
           ↓
NetworkAgent starts monitoring loop:
    every 60s:
        1. probe("zoom.us")
        2. check latency < 100ms ✓
        3. check loss < 1.0% ✓
        4. record baseline snapshot
        5. sleep(60)
           ↓
Violation detected:
    latency = 150ms (threshold 100ms)
           ↓
NetworkAgent._diagnose():
    - Create Incident
    - Severity: "high" (150/100 = 1.5x)
    - Run full diagnosis (traceroute + AS lookup)
           ↓
NetworkAgent._execute_actions():
    - Check alert cooldown ✓
    - Send alert (log warning for now)
    - Record incident
    - Update last_alert_time
```

---

## Safety Guardrails

The system enforces multiple layers of safety to prevent runaway automation:

### Rate Limits
- **Alert cooldown:** 300s between alerts per intent (prevents spam)
- **Max alerts/hour:** 10 (prevents alert storms)
- **Max diagnoses/hour:** 6 (prevents excessive probing)

### Auto-Protection
- **Consecutive failure tracking:** Counts failures per intent
- **Auto-disable:** After 5 consecutive failures, intent is disabled
- **Success reset:** Any success resets failure counter to 0

### Execution Validation
- Every action checked against guardrails before execution
- Blocked actions return reason (e.g., "Alert cooldown active (300s)")
- Guardrail state persists across agent restarts (in memory)

### User Control
- Users can view guardrail status via `get_guardrail_status()`
- Users can remove/reset intents to clear state
- Agent can be stopped at any time

---

## Plan Types & Examples

### 1. Simple Threshold
**Goal:** `"Alert me if Zoom latency exceeds 100ms"`

**Plan:**
- Monitor zoom.us latency
- Threshold: 100ms, comparison: ">"
- Actions: alert on violation
- Guardrails: alert_cooldown_300s, max_alerts_per_hour_10

### 2. Baseline Tracking
**Goal:** `"My connection should stay close to baseline"`

**Plan:**
- Monitor baseline_deviation
- Threshold: 1.5x (tight threshold for "close")
- Actions: monitor, record continuous, diagnose on deviation
- Guardrails: alert_cooldown_300s, require_baseline_samples_5

### 3. Diagnostic Goal
**Goal:** `"Diagnose whenever Netflix buffers"`

**Plan:**
- Monitor netflix.com latency
- Threshold: 100ms (default)
- Actions: monitor, diagnose (full_analysis=True), record incidents
- Guardrails: max_diagnoses_per_hour_6, alert_cooldown_300s

### 4. Continuous Quality
**Goal:** `"Gaming should never lag"`

**Plan:**
- Monitor gaming latency AND loss
- Thresholds: latency<100ms, loss<1.0%
- Actions: monitor, record, diagnose, alert
- Guardrails: alert_cooldown_300s, max_alerts_per_hour_10, auto_disable_on_persistent_failure

---

## Test Coverage

### Total: 378 tests

**Agent System (31 tests):**
- Intent parsing: 7 tests
- Agent lifecycle: 5 tests
- Metric extraction: 3 tests
- Incident management: 4 tests
- Autonomous planning: 8 tests
- Guardrail enforcement: 6 tests

**Consumer Mode (27 tests):**
- Edge collector: 12 tests
- Baseline tracking: 8 tests
- WiFi stats: 3 tests
- Speedtest: 2 tests
- Context enrichment: 2 tests

**Operator Mode (320 tests):**
- SSH collector: 45 tests
- Prometheus collector: 38 tests
- Path finding: 52 tests
- Trend analysis: 67 tests
- Anomaly detection: 58 tests
- Root cause analysis: 60 tests

---

## Key Design Decisions

### 1. Dual-Mode Architecture
**Decision:** Separate operator mode (SSH/Prometheus) from consumer mode (edge diagnostics)

**Rationale:**
- Different audiences: network admins vs home users
- Different data sources: device access vs edge probes
- Same intelligence layer works for both

### 2. Natural Language Planning
**Decision:** Generate plans from goals, don't execute immediately

**Rationale:**
- Users can review before committing
- Builds trust through transparency
- Confidence scoring shows system's certainty
- Allows plan refinement without trial-and-error

### 3. Guardrails Over Permissions
**Decision:** Enforce safety via rate limits and auto-disable, not user prompts

**Rationale:**
- Autonomous systems need automatic safety
- User interruptions defeat the purpose
- Clear guardrails are predictable
- Can be overridden by removing/resetting intents

### 4. Ring Buffer Baselines
**Decision:** Store last 100 snapshots, calculate statistics on-demand

**Rationale:**
- Simple, no time-series DB needed
- Works offline (JSON file)
- Fast anomaly detection (z-score)
- Automatic cleanup via ring buffer

### 5. Team Cymru for BGP
**Decision:** Use DNS-based AS lookup (Team Cymru)

**Rationale:**
- Free, no registration or API keys
- High availability (DNS infrastructure)
- Returns ASN, AS name, country
- Fallback-friendly (fails gracefully)

---

## Future Enhancements

### Short-term
- Slack/email/webhook alerts (currently logs only)
- Web dashboard for agent status
- Intent priority scheduling
- Baseline auto-tuning (adaptive thresholds)

### Medium-term
- Multi-target monitoring (probe multiple services per intent)
- Historical incident analysis
- ML-based anomaly detection
- Intent templates ("Use case: video conferencing")

### Long-term
- Auto-remediation (restart services, failover)
- Predictive maintenance
- Cross-intent correlation (incident cascades)
- Natural language incident reports

---

## Performance

### Consumer Mode Overhead
- Edge probe (ping + DNS + traceroute): ~2-5 seconds
- Baseline snapshot: <1ms (JSON write)
- Agent loop (60s interval): negligible CPU

### Operator Mode Overhead
- SSH command: 200-500ms per device
- Prometheus query: 50-200ms
- Trend analysis: <10ms (15 samples)
- Anomaly detection: <5ms per metric

### Memory Usage
- Agent: ~5MB
- Baseline storage: ~100KB (100 snapshots)
- Incident log: ~10KB per 100 incidents
- Total: <10MB for typical usage

---

## Deployment

### Claude Desktop (Recommended)
```json
{
  "mcpServers": {
    "network-diagnostics": {
      "command": "mcp-network"
    }
  }
}
```

### Docker (Future)
```bash
docker run -d \
  -v ~/.mcp_network:/root/.mcp_network \
  mcp-network:latest \
  --agent-mode
```

### Kubernetes (Future)
- StatefulSet for agent persistence
- ConfigMap for topology
- Secret for credentials
- Service for metrics endpoint

---

## Credits

This architecture was inspired by:
- **OpenAI Function Calling** - Natural language → structured actions
- **Kubernetes Operators** - Declarative intent → reconciliation loop
- **Datadog/New Relic** - Anomaly detection + alerting
- **BGPView/Hurricane Electric** - BGP context enrichment

Built with:
- MCP SDK (Model Context Protocol)
- Netmiko (multi-vendor SSH)
- TextFSM (Cisco parsing)
- Team Cymru (BGP data)
