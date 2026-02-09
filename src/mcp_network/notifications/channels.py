"""Notification channel implementations."""

import aiohttp
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional, List
from .core import Notification, NotificationChannel


class SlackChannel(NotificationChannel):
    """Slack webhook notification channel."""

    def __init__(self, webhook_url: str, channel: Optional[str] = None):
        """Initialize Slack channel.

        Args:
            webhook_url: Slack incoming webhook URL
            channel: Optional channel to post to (overrides webhook default)
        """
        self.webhook_url = webhook_url
        self.channel = channel

    async def send(self, notification: Notification) -> bool:
        """Send notification to Slack."""
        payload = self._format_slack_message(notification)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def test(self) -> bool:
        """Test Slack webhook."""
        test_notification = Notification(
            title="Test Notification",
            summary="Testing Slack integration",
            severity="info",
            details={},
            incident_id=None,
            timestamp=datetime.now().timestamp(),
        )
        return await self.send(test_notification)

    def _format_slack_message(self, notification: Notification) -> dict:
        """Format notification as Slack message."""
        fields = []
        for key, value in notification.details.items():
            fields.append({
                "title": key,
                "value": str(value),
                "short": True
            })

        attachment = {
            "color": notification.get_severity_color(),
            "title": f"{notification.get_severity_emoji()} {notification.title}",
            "text": notification.summary,
            "fields": fields,
            "ts": int(notification.timestamp),
        }

        if notification.incident_id:
            attachment["footer"] = f"Incident ID: {notification.incident_id}"

        payload = {"attachments": [attachment]}

        if self.channel:
            payload["channel"] = self.channel

        return payload


class DiscordChannel(NotificationChannel):
    """Discord webhook notification channel."""

    def __init__(self, webhook_url: str):
        """Initialize Discord channel.

        Args:
            webhook_url: Discord webhook URL
        """
        self.webhook_url = webhook_url

    async def send(self, notification: Notification) -> bool:
        """Send notification to Discord."""
        payload = self._format_discord_message(notification)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.webhook_url, json=payload) as resp:
                    return resp.status in (200, 204)
        except Exception:
            return False

    async def test(self) -> bool:
        """Test Discord webhook."""
        test_notification = Notification(
            title="Test Notification",
            summary="Testing Discord integration",
            severity="info",
            details={},
            incident_id=None,
            timestamp=datetime.now().timestamp(),
        )
        return await self.send(test_notification)

    def _format_discord_message(self, notification: Notification) -> dict:
        """Format notification as Discord embed."""
        fields = []
        for key, value in notification.details.items():
            fields.append({
                "name": key,
                "value": str(value),
                "inline": True
            })

        embed = {
            "title": f"{notification.get_severity_emoji()} {notification.title}",
            "description": notification.summary,
            "color": int(notification.get_severity_color().lstrip("#"), 16),
            "fields": fields,
            "timestamp": datetime.fromtimestamp(notification.timestamp).isoformat(),
        }

        if notification.incident_id:
            embed["footer"] = {"text": f"Incident: {notification.incident_id}"}

        return {"embeds": [embed]}


class EmailChannel(NotificationChannel):
    """Email notification channel via SMTP."""

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: List[str],
        use_tls: bool = True,
    ):
        """Initialize email channel.

        Args:
            smtp_host: SMTP server hostname
            smtp_port: SMTP server port
            username: SMTP username
            password: SMTP password
            from_addr: Sender email address
            to_addrs: List of recipient email addresses
            use_tls: Use TLS encryption (default True)
        """
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.to_addrs = to_addrs
        self.use_tls = use_tls

    async def send(self, notification: Notification) -> bool:
        """Send notification via email."""
        try:
            msg = self._format_email(notification)

            if self.use_tls:
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.starttls()
                    server.login(self.username, self.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.login(self.username, self.password)
                    server.send_message(msg)

            return True
        except Exception:
            return False

    async def test(self) -> bool:
        """Test email configuration."""
        test_notification = Notification(
            title="Test Notification",
            summary="Testing email integration",
            severity="info",
            details={},
            incident_id=None,
            timestamp=datetime.now().timestamp(),
        )
        return await self.send(test_notification)

    def _format_email(self, notification: Notification) -> MIMEMultipart:
        """Format notification as email."""
        msg = MIMEMultipart()
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.to_addrs)
        msg["Subject"] = f"[{notification.severity.upper()}] {notification.title}"

        body = f"""
{notification.get_severity_emoji()} {notification.title}

{notification.summary}

Details:
"""
        for key, value in notification.details.items():
            body += f"  {key}: {value}\n"

        if notification.incident_id:
            body += f"\nIncident ID: {notification.incident_id}"

        body += f"\nTimestamp: {datetime.fromtimestamp(notification.timestamp).isoformat()}"

        msg.attach(MIMEText(body, "plain"))
        return msg


class WebhookChannel(NotificationChannel):
    """Generic webhook notification channel."""

    def __init__(self, url: str, headers: Optional[dict] = None):
        """Initialize webhook channel.

        Args:
            url: Webhook URL
            headers: Optional HTTP headers
        """
        self.url = url
        self.headers = headers or {}

    async def send(self, notification: Notification) -> bool:
        """Send notification to webhook."""
        payload = {
            "title": notification.title,
            "summary": notification.summary,
            "severity": notification.severity,
            "details": notification.details,
            "incident_id": notification.incident_id,
            "timestamp": notification.timestamp,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.url,
                    json=payload,
                    headers=self.headers
                ) as resp:
                    return resp.status in (200, 201, 202, 204)
        except Exception:
            return False

    async def test(self) -> bool:
        """Test webhook."""
        test_notification = Notification(
            title="Test Notification",
            summary="Testing webhook integration",
            severity="info",
            details={},
            incident_id=None,
            timestamp=datetime.now().timestamp(),
        )
        return await self.send(test_notification)


class PagerDutyChannel(NotificationChannel):
    """PagerDuty Events API v2 notification channel."""

    def __init__(self, integration_key: str):
        """Initialize PagerDuty channel.

        Args:
            integration_key: PagerDuty integration key
        """
        self.integration_key = integration_key
        self.api_url = "https://events.pagerduty.com/v2/enqueue"

    async def send(self, notification: Notification) -> bool:
        """Send notification to PagerDuty."""
        payload = self._format_pagerduty_event(notification)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.api_url, json=payload) as resp:
                    return resp.status == 202
        except Exception:
            return False

    async def test(self) -> bool:
        """Test PagerDuty integration."""
        test_notification = Notification(
            title="Test Notification",
            summary="Testing PagerDuty integration",
            severity="info",
            details={},
            incident_id=None,
            timestamp=datetime.now().timestamp(),
        )
        return await self.send(test_notification)

    def _format_pagerduty_event(self, notification: Notification) -> dict:
        """Format notification as PagerDuty event."""
        # Map severity to PagerDuty severity
        pd_severity = {
            "critical": "critical",
            "warning": "warning",
            "info": "info",
        }.get(notification.severity, "info")

        # Trigger event for critical/warning, info for everything else
        event_action = "trigger" if notification.severity in ("critical", "warning") else "info"

        payload = {
            "routing_key": self.integration_key,
            "event_action": event_action,
            "payload": {
                "summary": notification.title,
                "severity": pd_severity,
                "source": "MCP Network Diagnostics",
                "timestamp": datetime.fromtimestamp(notification.timestamp).isoformat(),
                "custom_details": notification.details,
            },
        }

        if notification.incident_id:
            payload["dedup_key"] = notification.incident_id

        return payload
