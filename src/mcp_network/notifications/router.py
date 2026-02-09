"""Notification routing logic."""

from dataclasses import dataclass
from typing import Optional, List
from .core import Notification, NotificationChannel


@dataclass
class RoutingRule:
    """Rule for routing notifications to channels."""

    severity: Optional[List[str]] = None  # None = all severities
    event_types: Optional[List[str]] = None  # None = all types
    devices: Optional[List[str]] = None  # None = all devices
    channels: List[str] = None  # Channel names to notify

    def __post_init__(self):
        if self.channels is None:
            self.channels = []


class NotificationRouter:
    """Routes notifications to appropriate channels based on rules."""

    def __init__(self):
        self.channels: dict[str, NotificationChannel] = {}
        self.rules: list[RoutingRule] = []

    def add_channel(self, name: str, channel: NotificationChannel):
        """Add a notification channel.

        Args:
            name: Unique channel name
            channel: Channel instance
        """
        self.channels[name] = channel

    def remove_channel(self, name: str):
        """Remove a notification channel.

        Args:
            name: Channel name to remove
        """
        if name in self.channels:
            del self.channels[name]

    def add_rule(self, rule: RoutingRule):
        """Add a routing rule.

        Args:
            rule: Routing rule to add
        """
        self.rules.append(rule)

    def clear_rules(self):
        """Clear all routing rules."""
        self.rules = []

    async def route(self, notification: Notification):
        """Route notification to appropriate channels.

        Evaluates all rules and sends to matching channels.

        Args:
            notification: Notification to route
        """
        channels_to_notify = set()

        # Find all matching channels
        for rule in self.rules:
            if self._matches(rule, notification):
                channels_to_notify.update(rule.channels)

        # Send to all matching channels
        for channel_name in channels_to_notify:
            channel = self.channels.get(channel_name)
            if channel:
                try:
                    await channel.send(notification)
                except Exception:
                    # Log error but continue with other channels
                    pass

    def _matches(self, rule: RoutingRule, notification: Notification) -> bool:
        """Check if notification matches routing rule.

        Args:
            rule: Routing rule
            notification: Notification to check

        Returns:
            True if notification matches rule, False otherwise
        """
        # Check severity
        if rule.severity and notification.severity not in rule.severity:
            return False

        # Check event types (if notification has type in details)
        if rule.event_types:
            event_type = notification.details.get("event_type")
            if event_type and event_type not in rule.event_types:
                return False

        # Check devices (if notification has device in details)
        if rule.devices:
            device_id = notification.details.get("device")
            if device_id and device_id not in rule.devices:
                return False

        return True
