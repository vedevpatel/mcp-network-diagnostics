"""Tests for notification system."""

import pytest
from datetime import datetime

from mcp_network.notifications import (
    Notification,
    NotificationChannel,
    NotificationRouter,
    RoutingRule,
)


class MockChannel(NotificationChannel):
    """Mock notification channel for testing."""

    def __init__(self):
        self.sent_notifications = []
        self.should_succeed = True

    async def send(self, notification: Notification) -> bool:
        if self.should_succeed:
            self.sent_notifications.append(notification)
            return True
        return False

    async def test(self) -> bool:
        return self.should_succeed


@pytest.fixture
def notification():
    """Create test notification."""
    return Notification(
        title="Test Alert",
        summary="This is a test",
        severity="warning",
        details={"device": "R1", "metric": "cpu"},
        incident_id="inc_001",
        timestamp=datetime.now().timestamp(),
    )


class TestNotification:
    """Tests for Notification model."""

    def test_notification_creation(self, notification):
        """Test creating a notification."""
        assert notification.title == "Test Alert"
        assert notification.severity == "warning"

    def test_severity_emoji(self, notification):
        """Test severity emoji mapping."""
        critical = Notification(
            title="Critical",
            summary="",
            severity="critical",
            details={},
            incident_id=None,
            timestamp=0,
        )
        assert critical.get_severity_emoji() == "🔴"

        warning = Notification(
            title="Warning",
            summary="",
            severity="warning",
            details={},
            incident_id=None,
            timestamp=0,
        )
        assert warning.get_severity_emoji() == "🟡"

        info = Notification(
            title="Info",
            summary="",
            severity="info",
            details={},
            incident_id=None,
            timestamp=0,
        )
        assert info.get_severity_emoji() == "🔵"

    def test_severity_color(self, notification):
        """Test severity color mapping."""
        critical = Notification(
            title="Critical",
            summary="",
            severity="critical",
            details={},
            incident_id=None,
            timestamp=0,
        )
        assert critical.get_severity_color() == "#FF0000"

        warning = Notification(
            title="Warning",
            summary="",
            severity="warning",
            details={},
            incident_id=None,
            timestamp=0,
        )
        assert warning.get_severity_color() == "#FFA500"


class TestNotificationRouter:
    """Tests for notification router."""

    def test_router_initialization(self):
        """Test router creation."""
        router = NotificationRouter()
        assert len(router.channels) == 0
        assert len(router.rules) == 0

    def test_add_channel(self):
        """Test adding a channel."""
        router = NotificationRouter()
        channel = MockChannel()

        router.add_channel("test_channel", channel)

        assert "test_channel" in router.channels
        assert router.channels["test_channel"] == channel

    def test_remove_channel(self):
        """Test removing a channel."""
        router = NotificationRouter()
        channel = MockChannel()

        router.add_channel("test_channel", channel)
        router.remove_channel("test_channel")

        assert "test_channel" not in router.channels

    def test_add_rule(self):
        """Test adding a routing rule."""
        router = NotificationRouter()
        rule = RoutingRule(
            severity=["critical"],
            channels=["pagerduty"],
        )

        router.add_rule(rule)

        assert len(router.rules) == 1
        assert router.rules[0].severity == ["critical"]

    def test_clear_rules(self):
        """Test clearing all rules."""
        router = NotificationRouter()
        rule = RoutingRule(severity=["critical"], channels=["pagerduty"])

        router.add_rule(rule)
        router.clear_rules()

        assert len(router.rules) == 0

    @pytest.mark.asyncio
    async def test_route_by_severity(self, notification):
        """Test routing based on severity."""
        router = NotificationRouter()

        critical_channel = MockChannel()
        warning_channel = MockChannel()

        router.add_channel("critical_channel", critical_channel)
        router.add_channel("warning_channel", warning_channel)

        # Rule: critical alerts go to critical_channel
        router.add_rule(RoutingRule(
            severity=["critical"],
            channels=["critical_channel"],
        ))

        # Rule: warning alerts go to warning_channel
        router.add_rule(RoutingRule(
            severity=["warning"],
            channels=["warning_channel"],
        ))

        await router.route(notification)  # warning severity

        assert len(critical_channel.sent_notifications) == 0
        assert len(warning_channel.sent_notifications) == 1

    @pytest.mark.asyncio
    async def test_route_by_device(self):
        """Test routing based on device."""
        router = NotificationRouter()

        r1_channel = MockChannel()
        r2_channel = MockChannel()

        router.add_channel("r1_channel", r1_channel)
        router.add_channel("r2_channel", r2_channel)

        router.add_rule(RoutingRule(
            devices=["R1"],
            channels=["r1_channel"],
        ))
        router.add_rule(RoutingRule(
            devices=["R2"],
            channels=["r2_channel"],
        ))

        notification = Notification(
            title="Test",
            summary="",
            severity="info",
            details={"device": "R1"},
            incident_id=None,
            timestamp=datetime.now().timestamp(),
        )

        await router.route(notification)

        assert len(r1_channel.sent_notifications) == 1
        assert len(r2_channel.sent_notifications) == 0

    @pytest.mark.asyncio
    async def test_route_multiple_channels(self, notification):
        """Test routing to multiple channels."""
        router = NotificationRouter()

        channel1 = MockChannel()
        channel2 = MockChannel()

        router.add_channel("channel1", channel1)
        router.add_channel("channel2", channel2)

        # Rule matches both channels
        router.add_rule(RoutingRule(
            severity=["warning"],
            channels=["channel1", "channel2"],
        ))

        await router.route(notification)

        assert len(channel1.sent_notifications) == 1
        assert len(channel2.sent_notifications) == 1

    @pytest.mark.asyncio
    async def test_route_no_matching_rules(self, notification):
        """Test routing with no matching rules."""
        router = NotificationRouter()
        channel = MockChannel()

        router.add_channel("channel", channel)
        router.add_rule(RoutingRule(
            severity=["critical"],  # notification is warning
            channels=["channel"],
        ))

        await router.route(notification)

        assert len(channel.sent_notifications) == 0

    @pytest.mark.asyncio
    async def test_route_handles_channel_failure(self, notification):
        """Test that routing continues if one channel fails."""
        router = NotificationRouter()

        failing_channel = MockChannel()
        failing_channel.should_succeed = False

        working_channel = MockChannel()

        router.add_channel("failing", failing_channel)
        router.add_channel("working", working_channel)

        router.add_rule(RoutingRule(
            severity=["warning"],
            channels=["failing", "working"],
        ))

        await router.route(notification)

        # Working channel should still receive notification
        assert len(working_channel.sent_notifications) == 1


class TestRoutingRule:
    """Tests for routing rule matching."""

    def test_rule_matches_severity(self):
        """Test rule matching by severity."""
        rule = RoutingRule(
            severity=["critical", "warning"],
            channels=["test"],
        )

        critical_notif = Notification(
            title="Critical",
            summary="",
            severity="critical",
            details={},
            incident_id=None,
            timestamp=0,
        )

        info_notif = Notification(
            title="Info",
            summary="",
            severity="info",
            details={},
            incident_id=None,
            timestamp=0,
        )

        router = NotificationRouter()
        assert router._matches(rule, critical_notif)
        assert not router._matches(rule, info_notif)

    def test_rule_matches_device(self):
        """Test rule matching by device."""
        rule = RoutingRule(
            devices=["R1", "R2"],
            channels=["test"],
        )

        r1_notif = Notification(
            title="Test",
            summary="",
            severity="info",
            details={"device": "R1"},
            incident_id=None,
            timestamp=0,
        )

        r3_notif = Notification(
            title="Test",
            summary="",
            severity="info",
            details={"device": "R3"},
            incident_id=None,
            timestamp=0,
        )

        router = NotificationRouter()
        assert router._matches(rule, r1_notif)
        assert not router._matches(rule, r3_notif)

    def test_rule_matches_all_conditions(self):
        """Test rule matching all conditions."""
        rule = RoutingRule(
            severity=["critical"],
            devices=["R1"],
            channels=["test"],
        )

        matching_notif = Notification(
            title="Test",
            summary="",
            severity="critical",
            details={"device": "R1"},
            incident_id=None,
            timestamp=0,
        )

        wrong_severity = Notification(
            title="Test",
            summary="",
            severity="warning",
            details={"device": "R1"},
            incident_id=None,
            timestamp=0,
        )

        wrong_device = Notification(
            title="Test",
            summary="",
            severity="critical",
            details={"device": "R2"},
            incident_id=None,
            timestamp=0,
        )

        router = NotificationRouter()
        assert router._matches(rule, matching_notif)
        assert not router._matches(rule, wrong_severity)
        assert not router._matches(rule, wrong_device)

    def test_rule_with_none_matches_all(self):
        """Test that None values match everything."""
        rule = RoutingRule(
            severity=None,  # Match all severities
            devices=None,   # Match all devices
            channels=["test"],
        )

        notif = Notification(
            title="Test",
            summary="",
            severity="critical",
            details={"device": "R1"},
            incident_id=None,
            timestamp=0,
        )

        router = NotificationRouter()
        assert router._matches(rule, notif)
