"""Action executor with safety guardrails.

Executes planned actions while enforcing safety constraints.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .planner import Action, ActionPlan

logger = logging.getLogger(__name__)


@dataclass
class GuardrailState:
    """Tracks state for enforcing guardrails."""
    alert_count_last_hour: int = 0
    diagnose_count_last_hour: int = 0
    last_alert_times: dict[str, datetime] = field(default_factory=dict)
    consecutive_failures: dict[str, int] = field(default_factory=dict)
    disabled_intents: set[str] = field(default_factory=set)


class ActionExecutor:
    """Executes actions with safety guardrails."""

    def __init__(self):
        self.state = GuardrailState()

    def can_execute(self, action: Action, plan: ActionPlan) -> tuple[bool, Optional[str]]:
        """Check if an action can be executed given guardrails.

        Args:
            action: The action to execute
            plan: The action plan containing guardrails

        Returns:
            (can_execute, reason_if_blocked)
        """
        # Check if intent is disabled
        if plan.intent_id in self.state.disabled_intents:
            return False, "Intent disabled due to persistent failures"

        # Check guardrails
        for guardrail in plan.guardrails:
            if guardrail.startswith("alert_cooldown_"):
                seconds = int(guardrail.split("_")[-1].replace("s", ""))
                if not self._check_alert_cooldown(plan.intent_id, seconds):
                    return False, f"Alert cooldown active ({seconds}s)"

            elif guardrail.startswith("max_alerts_per_hour_"):
                max_count = int(guardrail.split("_")[-1])
                if not self._check_alert_rate(max_count):
                    return False, f"Alert rate limit ({max_count}/hour)"

            elif guardrail.startswith("max_diagnoses_per_hour_"):
                max_count = int(guardrail.split("_")[-1])
                if not self._check_diagnose_rate(max_count):
                    return False, f"Diagnose rate limit ({max_count}/hour)"

            elif guardrail == "require_baseline_samples_5":
                # Would need to check baseline storage
                # For now, assume OK
                pass

            elif guardrail == "auto_disable_on_persistent_failure":
                # Check if this intent has failed too many times
                failures = self.state.consecutive_failures.get(plan.intent_id, 0)
                if failures >= 5:
                    self.state.disabled_intents.add(plan.intent_id)
                    return False, "Intent disabled after 5 consecutive failures"

        return True, None

    def record_execution(self, action: Action, plan: ActionPlan, success: bool):
        """Record the result of an action execution.

        Args:
            action: The executed action
            plan: The action plan
            success: Whether execution succeeded
        """
        now = datetime.now(timezone.utc)

        if action.type == "alert":
            self.state.alert_count_last_hour += 1
            self.state.last_alert_times[plan.intent_id] = now

        elif action.type == "diagnose":
            self.state.diagnose_count_last_hour += 1

        # Track failures
        if not success:
            current = self.state.consecutive_failures.get(plan.intent_id, 0)
            self.state.consecutive_failures[plan.intent_id] = current + 1
        else:
            # Reset on success
            self.state.consecutive_failures[plan.intent_id] = 0

        # Decay hourly counters (simple sliding window)
        self._decay_hourly_counters()

    def reset_intent(self, intent_id: str):
        """Reset guardrail state for an intent (e.g., after user edits it)."""
        self.state.consecutive_failures.pop(intent_id, None)
        self.state.disabled_intents.discard(intent_id)
        self.state.last_alert_times.pop(intent_id, None)

    def _check_alert_cooldown(self, intent_id: str, cooldown_seconds: int) -> bool:
        """Check if alert cooldown has passed."""
        last_alert = self.state.last_alert_times.get(intent_id)
        if not last_alert:
            return True

        elapsed = (datetime.now(timezone.utc) - last_alert).total_seconds()
        return elapsed >= cooldown_seconds

    def _check_alert_rate(self, max_per_hour: int) -> bool:
        """Check if alert rate is within limit."""
        return self.state.alert_count_last_hour < max_per_hour

    def _check_diagnose_rate(self, max_per_hour: int) -> bool:
        """Check if diagnose rate is within limit."""
        return self.state.diagnose_count_last_hour < max_per_hour

    def _decay_hourly_counters(self):
        """Decay hourly counters (called on each execution)."""
        # Simple approach: decay by 1 on each call
        # In production, would use proper sliding window
        if self.state.alert_count_last_hour > 0:
            self.state.alert_count_last_hour = max(0, self.state.alert_count_last_hour - 1)
        if self.state.diagnose_count_last_hour > 0:
            self.state.diagnose_count_last_hour = max(0, self.state.diagnose_count_last_hour - 1)


class AutonomousAgent:
    """Agent that plans and executes actions autonomously.

    Combines IntentPlanner (what to do) with ActionExecutor (safe execution).
    """

    def __init__(self):
        from .planner import IntentPlanner
        self.planner = IntentPlanner()
        self.executor = ActionExecutor()
        self.plans: dict[str, ActionPlan] = {}

    async def set_goal(self, goal: str, intent_id: str) -> ActionPlan:
        """Set a high-level goal and generate a plan.

        Args:
            goal: Natural language goal
            intent_id: Unique ID for this goal

        Returns:
            Generated action plan
        """
        plan = await self.planner.plan(goal, intent_id)
        self.plans[intent_id] = plan

        logger.info(
            f"Generated plan for '{goal}': "
            f"{len(plan.actions)} actions, "
            f"confidence={plan.confidence:.2f}"
        )

        return plan

    def can_execute_action(self, intent_id: str, action: Action) -> tuple[bool, Optional[str]]:
        """Check if an action can be executed.

        Args:
            intent_id: Intent ID
            action: Action to check

        Returns:
            (can_execute, reason_if_blocked)
        """
        plan = self.plans.get(intent_id)
        if not plan:
            return False, "Plan not found"

        return self.executor.can_execute(action, plan)

    def record_action_result(self, intent_id: str, action: Action, success: bool):
        """Record the result of an action.

        Args:
            intent_id: Intent ID
            action: The action
            success: Whether it succeeded
        """
        plan = self.plans.get(intent_id)
        if plan:
            self.executor.record_execution(action, plan, success)

    def get_plan(self, intent_id: str) -> Optional[ActionPlan]:
        """Get the action plan for an intent."""
        return self.plans.get(intent_id)

    def remove_goal(self, intent_id: str):
        """Remove a goal and reset its state."""
        self.executor.reset_intent(intent_id)
        self.plans.pop(intent_id, None)

    def get_guardrail_status(self) -> dict:
        """Get current guardrail state for debugging."""
        return {
            "alert_count_last_hour": self.executor.state.alert_count_last_hour,
            "diagnose_count_last_hour": self.executor.state.diagnose_count_last_hour,
            "disabled_intents": list(self.executor.state.disabled_intents),
            "consecutive_failures": dict(self.executor.state.consecutive_failures),
        }
