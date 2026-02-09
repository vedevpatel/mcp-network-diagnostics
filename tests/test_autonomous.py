"""Tests for autonomous agent planning and execution."""

import asyncio

from mcp_network.agent import AutonomousAgent, IntentPlanner, ActionExecutor, Action, ActionPlan


def _run(coro):
    """Run async code in sync test context."""
    return asyncio.run(coro)


# ============================================================================
# Intent Planner Tests
# ============================================================================

def test_planner_simple_threshold():
    """Test planning for simple threshold goals."""
    planner = IntentPlanner()

    plan = _run(planner.plan("Alert me if Zoom latency exceeds 100ms", "test1"))

    assert plan.intent_id == "test1"
    assert plan.confidence >= 0.8
    assert len(plan.actions) >= 1

    # Should have a monitor action
    monitor = next((a for a in plan.actions if a.type == "monitor"), None)
    assert monitor is not None
    assert monitor.target == "zoom.us"
    assert monitor.metric == "latency"
    assert monitor.threshold == 100.0
    assert monitor.comparison == ">"

    # Should have alert action since user said "alert me"
    alert = next((a for a in plan.actions if a.type == "alert"), None)
    assert alert is not None


def test_planner_baseline_tracking():
    """Test planning for baseline deviation goals."""
    planner = IntentPlanner()

    plan = _run(planner.plan("My connection should stay close to baseline", "test2"))

    assert plan.confidence >= 0.7
    monitor = next((a for a in plan.actions if a.type == "monitor"), None)
    assert monitor.metric == "baseline_deviation"
    assert monitor.threshold <= 2.0  # "close" means tight threshold

    # Should include record action
    record = next((a for a in plan.actions if a.type == "record"), None)
    assert record is not None


def test_planner_diagnostic_goal():
    """Test planning for diagnostic goals."""
    planner = IntentPlanner()

    plan = _run(planner.plan("Diagnose whenever Netflix is slow", "test3"))

    assert len(plan.actions) >= 2

    monitor = next((a for a in plan.actions if a.type == "monitor"), None)
    assert monitor is not None
    assert monitor.target == "netflix.com"

    # Should have diagnose action
    diagnose = next((a for a in plan.actions if a.type == "diagnose"), None)
    assert diagnose is not None
    assert diagnose.params.get("on") == "violation"


def test_planner_continuous_quality():
    """Test planning for continuous quality goals."""
    planner = IntentPlanner()

    plan = _run(planner.plan("Gaming should never lag", "test4"))

    assert len(plan.actions) >= 3  # monitor + diagnose + alert/record

    # Should monitor both latency and loss
    actions = plan.actions
    assert any(a.type == "monitor" and a.metric == "latency" for a in actions)


def test_planner_target_extraction():
    """Test target service extraction."""
    planner = IntentPlanner()

    plan = _run(planner.plan("Keep Teams responsive", "test5"))
    monitor = next((a for a in plan.actions if a.type == "monitor"), None)
    assert monitor.target == "teams.microsoft.com"

    plan = _run(planner.plan("Discord should be fast", "test6"))
    monitor = next((a for a in plan.actions if a.type == "monitor"), None)
    assert monitor.target == "discord.com"


def test_planner_metric_extraction():
    """Test metric extraction from goals."""
    planner = IntentPlanner()

    plan = _run(planner.plan("Alert on packet loss", "test7"))
    monitor = next((a for a in plan.actions if a.type == "monitor"), None)
    assert monitor.metric == "loss"

    plan = _run(planner.plan("DNS resolution is slow", "test8"))
    monitor = next((a for a in plan.actions if a.type == "monitor"), None)
    assert monitor.metric == "dns_time"


def test_planner_threshold_extraction():
    """Test threshold extraction from text."""
    planner = IntentPlanner()

    plan = _run(planner.plan("Latency exceeds 50ms", "test9"))
    monitor = next((a for a in plan.actions if a.type == "monitor"), None)
    assert monitor.threshold == 50.0

    plan = _run(planner.plan("Packet loss over 5%", "test10"))
    monitor = next((a for a in plan.actions if a.type == "monitor"), None)
    assert monitor.threshold == 5.0


def test_planner_guardrails():
    """Test that plans include appropriate guardrails."""
    planner = IntentPlanner()

    plan = _run(planner.plan("Alert me if Zoom lags", "test11"))

    # Should have alert cooldown
    assert any("alert_cooldown" in g for g in plan.guardrails)

    # Should have rate limits
    assert len(plan.guardrails) >= 1


# ============================================================================
# Action Executor Tests
# ============================================================================

def test_executor_alert_cooldown():
    """Test alert cooldown enforcement."""
    executor = ActionExecutor()

    action = Action(type="alert")
    plan = ActionPlan(
        intent_id="test1",
        goal="test",
        actions=[action],
        triggers=["periodic"],
        guardrails=["alert_cooldown_300s"],
        confidence=0.9,
        explanation="test",
    )

    # First alert should be allowed
    can_execute, reason = executor.can_execute(action, plan)
    assert can_execute

    # Record the alert
    executor.record_execution(action, plan, success=True)

    # Second alert should be blocked (cooldown active)
    can_execute, reason = executor.can_execute(action, plan)
    assert not can_execute
    assert "cooldown" in reason.lower()


def test_executor_alert_rate_limit():
    """Test alert rate limiting."""
    executor = ActionExecutor()

    action = Action(type="alert")
    plan = ActionPlan(
        intent_id="test2",
        goal="test",
        actions=[action],
        triggers=["periodic"],
        guardrails=["max_alerts_per_hour_3"],
        confidence=0.9,
        explanation="test",
    )

    # Simulate 3 alerts
    for i in range(3):
        executor.state.alert_count_last_hour = i
        can_execute, _ = executor.can_execute(action, plan)
        assert can_execute  # Should allow up to 3

    # 4th alert should be blocked
    executor.state.alert_count_last_hour = 3
    can_execute, reason = executor.can_execute(action, plan)
    assert not can_execute
    assert "rate limit" in reason.lower()


def test_executor_persistent_failure_disable():
    """Test auto-disable on persistent failures."""
    executor = ActionExecutor()

    action = Action(type="monitor")
    plan = ActionPlan(
        intent_id="test3",
        goal="test",
        actions=[action],
        triggers=["periodic"],
        guardrails=["auto_disable_on_persistent_failure"],
        confidence=0.9,
        explanation="test",
    )

    # Simulate 4 failures (should still work)
    for i in range(4):
        executor.record_execution(action, plan, success=False)
        can_execute, _ = executor.can_execute(action, plan)
        assert can_execute

    # 5th failure should disable the intent
    executor.record_execution(action, plan, success=False)
    can_execute, reason = executor.can_execute(action, plan)
    assert not can_execute
    assert "disabled" in reason.lower()


def test_executor_success_resets_failures():
    """Test that success resets failure counter."""
    executor = ActionExecutor()

    action = Action(type="monitor")
    plan = ActionPlan(
        intent_id="test4",
        goal="test",
        actions=[action],
        triggers=["periodic"],
        guardrails=["auto_disable_on_persistent_failure"],
        confidence=0.9,
        explanation="test",
    )

    # 3 failures
    for i in range(3):
        executor.record_execution(action, plan, success=False)

    assert executor.state.consecutive_failures["test4"] == 3

    # Then success
    executor.record_execution(action, plan, success=True)

    # Counter should reset
    assert executor.state.consecutive_failures["test4"] == 0


def test_executor_reset_intent():
    """Test resetting intent state."""
    executor = ActionExecutor()

    executor.state.consecutive_failures["test5"] = 5
    executor.state.disabled_intents.add("test5")

    executor.reset_intent("test5")

    assert "test5" not in executor.state.consecutive_failures
    assert "test5" not in executor.state.disabled_intents


# ============================================================================
# Autonomous Agent Tests
# ============================================================================

def test_autonomous_agent_set_goal():
    """Test setting a goal and generating a plan."""
    agent = AutonomousAgent()

    plan = _run(agent.set_goal("Zoom should never lag", "test1"))

    assert plan.intent_id == "test1"
    assert plan.goal == "Zoom should never lag"
    assert plan.confidence > 0.0
    assert len(plan.actions) > 0
    assert len(plan.guardrails) > 0


def test_autonomous_agent_plan_storage():
    """Test that plans are stored and retrievable."""
    agent = AutonomousAgent()

    _run(agent.set_goal("Keep Netflix smooth", "test2"))

    plan = agent.get_plan("test2")
    assert plan is not None
    assert plan.intent_id == "test2"


def test_autonomous_agent_can_execute():
    """Test checking if actions can execute."""
    agent = AutonomousAgent()

    _run(agent.set_goal("Alert on high latency", "test3"))

    # Get a monitor action from the plan
    plan = agent.get_plan("test3")
    action = next((a for a in plan.actions if a.type == "monitor"), None)

    # Should be able to execute initially
    can_execute, _ = agent.can_execute_action("test3", action)
    assert can_execute


def test_autonomous_agent_record_result():
    """Test recording action results."""
    agent = AutonomousAgent()

    _run(agent.set_goal("Test goal", "test4"))

    plan = agent.get_plan("test4")
    action = plan.actions[0]

    # Record success
    agent.record_action_result("test4", action, success=True)

    # Should not have failures
    assert agent.executor.state.consecutive_failures.get("test4", 0) == 0


def test_autonomous_agent_remove_goal():
    """Test removing a goal."""
    agent = AutonomousAgent()

    _run(agent.set_goal("Temporary goal", "test5"))

    assert agent.get_plan("test5") is not None

    agent.remove_goal("test5")

    assert agent.get_plan("test5") is None


def test_autonomous_agent_guardrail_status():
    """Test getting guardrail status."""
    agent = AutonomousAgent()

    status = agent.get_guardrail_status()

    assert "alert_count_last_hour" in status
    assert "diagnose_count_last_hour" in status
    assert "disabled_intents" in status
    assert "consecutive_failures" in status
