"""Core autonomous monitoring agent.

Continuously monitors network state, checks intents, and takes action.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from mcp_network.baseline.storage import BaselineStorage
from mcp_network.collectors.edge import EdgeCollector
from mcp_network.tools import _analyze_edge_probe

from .intents import Intent, IntentParser

logger = logging.getLogger(__name__)


@dataclass
class AgentConfig:
    """Configuration for the network monitoring agent."""
    poll_interval: float = 60.0  # seconds between checks
    baseline_path: Optional[str] = None  # override default baseline path
    alert_cooldown: float = 300.0  # seconds between repeat alerts
    max_incidents_retained: int = 100


@dataclass
class Incident:
    """A detected network issue."""
    id: str
    intent_id: str
    timestamp: datetime
    metric: str
    target: str
    current_value: float
    threshold: float
    comparison: str
    severity: str  # "low", "medium", "high"
    diagnosis: Optional[dict] = None
    actions_taken: list[str] = field(default_factory=list)


class NetworkAgent:
    """Autonomous network monitoring agent.

    Continuously:
    1. Collects network state (ping, DNS, traceroute)
    2. Checks intents against current state
    3. Diagnoses violations
    4. Takes action (alert, record, diagnose)
    5. Updates baselines
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or AgentConfig()
        self.collector = EdgeCollector()
        self.baseline = BaselineStorage(storage_path=self.config.baseline_path)
        self.intents: dict[str, Intent] = {}
        self.incidents: list[Incident] = []
        self.running = False
        self._last_alert_time: dict[str, datetime] = {}
        self._task: Optional[asyncio.Task] = None

    def add_intent(self, intent: Intent):
        """Register a new monitoring intent."""
        self.intents[intent.id] = intent
        logger.info(f"Added intent: {intent.name}")

    def remove_intent(self, intent_id: str):
        """Remove a monitoring intent."""
        if intent_id in self.intents:
            del self.intents[intent_id]
            logger.info(f"Removed intent: {intent_id}")

    def get_intents(self) -> list[Intent]:
        """Get all registered intents."""
        return list(self.intents.values())

    def get_incidents(self, limit: Optional[int] = None) -> list[Incident]:
        """Get recent incidents."""
        if limit:
            return self.incidents[-limit:]
        return self.incidents

    async def start(self):
        """Start the monitoring loop in the background."""
        if self.running:
            logger.warning("Agent already running")
            return

        self.running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Network monitoring agent started")

    async def stop(self):
        """Stop the monitoring loop."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Network monitoring agent stopped")

    async def _run_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                await self._collect_state()
                violations = await self._check_intents()

                for violation in violations:
                    incident = await self._diagnose(violation)
                    await self._execute_actions(incident)

                await self._update_baseline()

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}", exc_info=True)

            await asyncio.sleep(self.config.poll_interval)

    async def _collect_state(self):
        """Collect current network state."""
        # Probe key targets from intents
        targets = set()
        for intent in self.intents.values():
            if intent.enabled and intent.target != "all":
                # Extract domain from target (e.g., "zoom.us")
                if "." in intent.target:
                    targets.add(intent.target)

        # Always probe a baseline target
        if not targets:
            targets.add("8.8.8.8")

        # Run probes (store for intent checking)
        self._current_probes = {}
        for target in targets:
            try:
                probe = await self.collector.probe_destination(target)
                self._current_probes[target] = probe
            except Exception as e:
                logger.error(f"Failed to probe {target}: {e}")

    async def _check_intents(self) -> list[tuple[Intent, dict]]:
        """Check all intents against current state.

        Returns:
            List of (intent, violation_data) tuples
        """
        violations = []

        for intent in self.intents.values():
            if not intent.enabled:
                continue

            # Get relevant probe data
            probe = None
            if intent.target == "all":
                # Use first available probe
                probe = next(iter(self._current_probes.values()), None)
            else:
                probe = self._current_probes.get(intent.target)

            if not probe:
                continue

            # Extract metric value
            value = self._extract_metric(probe, intent.metric)
            if value is None:
                continue

            # Check threshold
            violated = self._check_threshold(
                value, intent.threshold, intent.comparison
            )

            if violated:
                violations.append((intent, {
                    "probe": probe,
                    "metric": intent.metric,
                    "value": value,
                    "threshold": intent.threshold,
                }))

        return violations

    def _extract_metric(self, probe, metric: str) -> Optional[float]:
        """Extract a metric value from probe data."""
        if metric == "latency":
            # Use gateway latency as primary latency metric
            if probe.gateway and probe.gateway.latency_ms:
                return probe.gateway.latency_ms
            # Or HTTP TTFB
            if probe.http and probe.http.ttfb_ms:
                return probe.http.ttfb_ms
        elif metric == "loss":
            if probe.gateway and probe.gateway.loss_pct is not None:
                return probe.gateway.loss_pct
        elif metric == "dns_time":
            if probe.dns and probe.dns.resolution_ms:
                return probe.dns.resolution_ms
        elif metric == "baseline_deviation":
            # Check if current latency deviates from baseline
            if probe.gateway and probe.gateway.latency_ms:
                current = probe.gateway.latency_ms
                baseline_data = self.baseline.load()
                if baseline_data and "ping_avg_ms" in baseline_data.get("averages", {}):
                    baseline_avg = baseline_data["averages"]["ping_avg_ms"]
                    if baseline_avg > 0:
                        return current / baseline_avg  # deviation factor

        return None

    def _check_threshold(self, value: float, threshold: float, comparison: str) -> bool:
        """Check if value violates threshold."""
        if comparison == "<":
            return value >= threshold  # violated if NOT less than
        elif comparison == ">":
            return value <= threshold  # violated if NOT greater than
        elif comparison == "==":
            return abs(value - threshold) > 0.01  # violated if not equal
        return False

    async def _diagnose(self, violation: tuple[Intent, dict]) -> Incident:
        """Diagnose a violation and create an incident."""
        intent, data = violation
        probe = data["probe"]

        # Generate incident ID
        import hashlib
        incident_id = hashlib.md5(
            f"{intent.id}:{datetime.now(timezone.utc).isoformat()}".encode()
        ).hexdigest()[:12]

        # Determine severity based on how much threshold was exceeded
        value = data["value"]
        threshold = data["threshold"]
        if intent.comparison in ("<", ">"):
            ratio = value / threshold if threshold > 0 else 1.0
            if ratio > 2.0 or ratio < 0.5:
                severity = "high"
            elif ratio > 1.5 or ratio < 0.67:
                severity = "medium"
            else:
                severity = "low"
        else:
            severity = "medium"

        # Run full diagnosis if requested
        diagnosis = None
        if "diagnose" in intent.actions:
            diagnosis = await _analyze_edge_probe(probe)

        incident = Incident(
            id=incident_id,
            intent_id=intent.id,
            timestamp=datetime.now(timezone.utc),
            metric=data["metric"],
            target=intent.target,
            current_value=value,
            threshold=threshold,
            comparison=intent.comparison,
            severity=severity,
            diagnosis=diagnosis,
        )

        # Store incident
        self.incidents.append(incident)
        if len(self.incidents) > self.config.max_incidents_retained:
            self.incidents.pop(0)

        logger.warning(
            f"Incident {incident.id}: {intent.name} - "
            f"{data['metric']}={value:.1f} (threshold={threshold})"
        )

        return incident

    async def _execute_actions(self, incident: Incident):
        """Execute actions for an incident."""
        intent = self.intents.get(incident.intent_id)
        if not intent:
            return

        # Check alert cooldown
        if "alert" in intent.actions:
            last_alert = self._last_alert_time.get(incident.intent_id)
            if last_alert:
                elapsed = (datetime.now(timezone.utc) - last_alert).total_seconds()
                if elapsed < self.config.alert_cooldown:
                    logger.debug(
                        f"Skipping alert for {incident.intent_id} "
                        f"(cooldown: {elapsed:.0f}s / {self.config.alert_cooldown:.0f}s)"
                    )
                    return

            await self._send_alert(incident, intent)
            self._last_alert_time[incident.intent_id] = datetime.now(timezone.utc)
            incident.actions_taken.append("alert")

        if "record" in intent.actions:
            # Recording happens automatically via baseline updates
            incident.actions_taken.append("record")

    async def _send_alert(self, incident: Incident, intent: Intent):
        """Send an alert for an incident.

        For now, just logs. Future: Slack, email, webhook.
        """
        message = (
            f"🚨 Network Alert: {intent.name}\n"
            f"Target: {incident.target}\n"
            f"Metric: {incident.metric} = {incident.current_value:.1f} "
            f"(threshold: {incident.threshold})\n"
            f"Severity: {incident.severity}\n"
            f"Time: {incident.timestamp.isoformat()}"
        )

        if incident.diagnosis:
            verdict = incident.diagnosis.get("verdict", "Unknown")
            message += f"\nDiagnosis: {verdict}"

        logger.warning(f"ALERT: {message}")
        # TODO: Send to Slack/email/webhook based on config

    async def _update_baseline(self):
        """Update baseline with current measurements."""
        # Record a baseline snapshot if we have probe data
        if not self._current_probes:
            return

        # Use the first probe as representative
        probe = next(iter(self._current_probes.values()))

        # Extract metrics
        snapshot = {}
        if probe.gateway:
            if probe.gateway.latency_ms is not None:
                snapshot["ping_avg_ms"] = probe.gateway.latency_ms
            if probe.gateway.loss_pct is not None:
                snapshot["ping_loss_pct"] = probe.gateway.loss_pct

        if probe.dns and probe.dns.resolution_ms is not None:
            snapshot["dns_time_ms"] = probe.dns.resolution_ms

        if snapshot:
            self.baseline.record_snapshot(snapshot)
