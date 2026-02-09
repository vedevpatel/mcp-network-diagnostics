"""Intent planning - converts goals to executable action plans.

Takes high-level user intent and generates concrete monitoring/action plans.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Action:
    """A concrete action to execute."""
    type: str  # "monitor", "alert", "diagnose", "record", "threshold_check"
    target: Optional[str] = None
    metric: Optional[str] = None
    threshold: Optional[float] = None
    comparison: Optional[str] = None
    interval_seconds: Optional[float] = None
    params: dict = field(default_factory=dict)


@dataclass
class ActionPlan:
    """A plan for achieving a user's intent."""
    intent_id: str
    goal: str  # Original user goal
    actions: list[Action]
    triggers: list[str]  # When to execute ("on_violation", "periodic", "on_change")
    guardrails: list[str]  # Safety constraints
    confidence: float  # How confident we are in this plan (0-1)
    explanation: str  # Human-readable explanation


class IntentPlanner:
    """Plans how to achieve user's network goals autonomously."""

    def __init__(self):
        # Common patterns for goal understanding
        self.service_targets = {
            "zoom": "zoom.us",
            "teams": "teams.microsoft.com",
            "meet": "meet.google.com",
            "slack": "slack.com",
            "discord": "discord.com",
            "gaming": "gaming",
            "netflix": "netflix.com",
            "youtube": "youtube.com",
            "streaming": "streaming",
        }

    async def plan(self, goal: str, intent_id: str) -> ActionPlan:
        """Generate an action plan from a natural language goal.

        Args:
            goal: User's goal in plain English
            intent_id: Unique ID for this intent

        Returns:
            ActionPlan with concrete actions
        """
        goal_lower = goal.lower()

        # Detect goal complexity
        if self._is_simple_threshold_goal(goal_lower):
            return self._plan_simple_threshold(goal, intent_id)
        elif self._is_baseline_goal(goal_lower):
            return self._plan_baseline_tracking(goal, intent_id)
        elif self._is_diagnostic_goal(goal_lower):
            return self._plan_diagnostic(goal, intent_id)
        elif self._is_continuous_quality_goal(goal_lower):
            return self._plan_continuous_quality(goal, intent_id)
        else:
            # Fallback: general monitoring
            return self._plan_general_monitoring(goal, intent_id)

    def _is_simple_threshold_goal(self, goal: str) -> bool:
        """Check if goal is a simple threshold check."""
        threshold_keywords = [
            "exceeds", "above", "over", "higher than", "below", "under",
            "less than", "stays under", "stays below", "never exceed"
        ]
        return any(kw in goal for kw in threshold_keywords)

    def _is_baseline_goal(self, goal: str) -> bool:
        """Check if goal involves baseline tracking."""
        baseline_keywords = [
            "baseline", "normal", "usual", "typical", "stays close",
            "deviates", "compared to usual"
        ]
        return any(kw in goal for kw in baseline_keywords)

    def _is_diagnostic_goal(self, goal: str) -> bool:
        """Check if goal requires diagnostic action."""
        diagnostic_keywords = [
            "diagnose", "investigate", "find out why", "figure out",
            "troubleshoot", "analyze when"
        ]
        return any(kw in goal for kw in diagnostic_keywords)

    def _is_continuous_quality_goal(self, goal: str) -> bool:
        """Check if goal is about continuous quality."""
        quality_keywords = [
            "should always", "should never", "must always", "must never",
            "keep", "maintain", "ensure", "guarantee"
        ]
        return any(kw in goal for kw in quality_keywords)

    def _plan_simple_threshold(self, goal: str, intent_id: str) -> ActionPlan:
        """Plan for simple threshold monitoring."""
        goal_lower = goal.lower()

        # Extract target service
        target = self._extract_target(goal_lower)

        # Extract metric
        metric = self._extract_metric(goal_lower)

        # Extract threshold
        threshold = self._extract_threshold(goal_lower)
        if threshold is None:
            # Defaults based on metric
            threshold = 100.0 if metric == "latency" else 5.0

        # Extract comparison
        comparison = self._extract_comparison(goal_lower)

        # Determine if user wants alerts
        wants_alert = any(kw in goal_lower for kw in ["alert", "notify", "tell me"])

        actions = [
            Action(
                type="monitor",
                target=target,
                metric=metric,
                threshold=threshold,
                comparison=comparison,
                interval_seconds=60.0,
            )
        ]

        if wants_alert:
            actions.append(Action(
                type="alert",
                params={"on": "violation"},
            ))

        return ActionPlan(
            intent_id=intent_id,
            goal=goal,
            actions=actions,
            triggers=["periodic"],
            guardrails=[
                "alert_cooldown_300s",
                "max_alerts_per_hour_10",
            ],
            confidence=0.9,
            explanation=f"Monitor {target} {metric}, alert if {comparison} {threshold}",
        )

    def _plan_baseline_tracking(self, goal: str, intent_id: str) -> ActionPlan:
        """Plan for baseline deviation monitoring."""
        goal_lower = goal.lower()

        target = self._extract_target(goal_lower)
        metric = "baseline_deviation"

        # Baseline deviation threshold (e.g., 2x worse than normal)
        threshold = 2.0
        if "close" in goal_lower:
            threshold = 1.5  # Tighter threshold
        elif "significantly" in goal_lower or "way" in goal_lower:
            threshold = 3.0  # Looser threshold

        actions = [
            Action(
                type="monitor",
                target=target,
                metric=metric,
                threshold=threshold,
                comparison="<",
                interval_seconds=60.0,
            ),
            Action(
                type="record",
                params={"continuous": True},
            ),
        ]

        # Auto-diagnose on significant deviation
        if threshold >= 2.0:
            actions.append(Action(
                type="diagnose",
                params={"on": "violation"},
            ))

        return ActionPlan(
            intent_id=intent_id,
            goal=goal,
            actions=actions,
            triggers=["periodic"],
            guardrails=[
                "alert_cooldown_300s",
                "require_baseline_samples_5",
            ],
            confidence=0.85,
            explanation=f"Track {target} baseline, alert if {threshold}x deviation",
        )

    def _plan_diagnostic(self, goal: str, intent_id: str) -> ActionPlan:
        """Plan for diagnostic-focused goals."""
        goal_lower = goal.lower()

        target = self._extract_target(goal_lower)
        metric = self._extract_metric(goal_lower)

        # Diagnostic goals trigger on any degradation
        threshold = 100.0 if metric == "latency" else 2.0
        if "when" in goal_lower:
            # "diagnose when latency exceeds X"
            extracted_threshold = self._extract_threshold(goal_lower)
            if extracted_threshold:
                threshold = extracted_threshold

        actions = [
            Action(
                type="monitor",
                target=target,
                metric=metric,
                threshold=threshold,
                comparison=">",
                interval_seconds=60.0,
            ),
            Action(
                type="diagnose",
                params={
                    "on": "violation",
                    "full_analysis": True,
                },
            ),
            Action(
                type="record",
                params={"incident_log": True},
            ),
        ]

        return ActionPlan(
            intent_id=intent_id,
            goal=goal,
            actions=actions,
            triggers=["on_violation"],
            guardrails=[
                "max_diagnoses_per_hour_6",
                "alert_cooldown_300s",
            ],
            confidence=0.8,
            explanation=f"Monitor {target} {metric}, diagnose when > {threshold}",
        )

    def _plan_continuous_quality(self, goal: str, intent_id: str) -> ActionPlan:
        """Plan for continuous quality assurance goals."""
        goal_lower = goal.lower()

        target = self._extract_target(goal_lower)

        # Quality goals are comprehensive
        actions = [
            Action(
                type="monitor",
                target=target,
                metric="latency",
                threshold=100.0,
                comparison="<",
                interval_seconds=60.0,
            ),
            Action(
                type="monitor",
                target=target,
                metric="loss",
                threshold=1.0,
                comparison="<",
                interval_seconds=60.0,
            ),
            Action(
                type="record",
                params={"continuous": True},
            ),
            Action(
                type="diagnose",
                params={
                    "on": "violation",
                    "priority": "high",
                },
            ),
            Action(
                type="alert",
                params={"on": "violation"},
            ),
        ]

        return ActionPlan(
            intent_id=intent_id,
            goal=goal,
            actions=actions,
            triggers=["periodic", "on_violation"],
            guardrails=[
                "alert_cooldown_300s",
                "max_alerts_per_hour_10",
                "auto_disable_on_persistent_failure",
            ],
            confidence=0.9,
            explanation=f"Comprehensive monitoring of {target} (latency + loss)",
        )

    def _plan_general_monitoring(self, goal: str, intent_id: str) -> ActionPlan:
        """Fallback plan for unclear goals."""
        goal_lower = goal.lower()

        target = self._extract_target(goal_lower)
        metric = self._extract_metric(goal_lower)

        actions = [
            Action(
                type="monitor",
                target=target,
                metric=metric,
                threshold=100.0,
                comparison="<",
                interval_seconds=60.0,
            ),
        ]

        return ActionPlan(
            intent_id=intent_id,
            goal=goal,
            actions=actions,
            triggers=["periodic"],
            guardrails=["alert_cooldown_300s"],
            confidence=0.6,
            explanation=f"General monitoring of {target} {metric}",
        )

    def _extract_target(self, goal: str) -> str:
        """Extract target service/destination from goal."""
        for keyword, target in self.service_targets.items():
            if keyword in goal:
                return target
        return "all"

    def _extract_metric(self, goal: str) -> str:
        """Extract metric from goal."""
        # Check DNS first (more specific than "slow")
        if any(kw in goal for kw in ["dns", "resolution", "lookup"]):
            return "dns_time"
        elif any(kw in goal for kw in ["baseline", "normal", "usual"]):
            return "baseline_deviation"
        elif any(kw in goal for kw in ["loss", "drop", "packet", "disconnect"]):
            return "loss"
        elif any(kw in goal for kw in ["lag", "latency", "ping", "slow", "delay"]):
            return "latency"
        return "latency"  # Default

    def _extract_threshold(self, goal: str) -> Optional[float]:
        """Extract numeric threshold from goal."""
        # Look for patterns like "50ms", "5%", "100"
        patterns = [
            r"(\d+(?:\.\d+)?)\s*ms",
            r"(\d+(?:\.\d+)?)\s*%",
            r"(\d+(?:\.\d+)?)\s+milliseconds",
            r"exceeds?\s+(\d+(?:\.\d+)?)",
            r"over\s+(\d+(?:\.\d+)?)",
            r"above\s+(\d+(?:\.\d+)?)",
            r"under\s+(\d+(?:\.\d+)?)",
            r"below\s+(\d+(?:\.\d+)?)",
        ]

        for pattern in patterns:
            match = re.search(pattern, goal)
            if match:
                return float(match.group(1))

        return None

    def _extract_comparison(self, goal: str) -> str:
        """Extract comparison operator from goal."""
        if any(kw in goal for kw in ["exceeds", "above", "over", "higher than", "more than"]):
            return ">"
        elif any(kw in goal for kw in ["below", "under", "less than", "stays under"]):
            return "<"
        elif any(kw in goal for kw in ["never exceed", "should never", "must not exceed"]):
            return "<"
        return "<"  # Default: keep metric below threshold
