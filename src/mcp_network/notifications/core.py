"""Core notification abstractions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Notification:
    """Notification message to be sent."""

    title: str
    summary: str
    severity: str  # critical, warning, info
    details: dict
    incident_id: Optional[str]
    timestamp: float

    def get_severity_emoji(self) -> str:
        """Get emoji for severity level."""
        return {
            "critical": "🔴",
            "warning": "🟡",
            "info": "🔵",
        }.get(self.severity, "⚪")

    def get_severity_color(self) -> str:
        """Get hex color for severity level."""
        return {
            "critical": "#FF0000",
            "warning": "#FFA500",
            "info": "#0000FF",
        }.get(self.severity, "#808080")


class NotificationChannel(ABC):
    """Abstract base class for notification channels."""

    @abstractmethod
    async def send(self, notification: Notification) -> bool:
        """Send notification through this channel.

        Args:
            notification: Notification to send

        Returns:
            True if sent successfully, False otherwise
        """
        pass

    @abstractmethod
    async def test(self) -> bool:
        """Test channel connectivity.

        Returns:
            True if channel is reachable, False otherwise
        """
        pass
