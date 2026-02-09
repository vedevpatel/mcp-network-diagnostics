"""Authorization and permission management."""

import re
from typing import Optional

from .auth import APIKey, Role


# Tool permissions by role (hierarchical)
TOOL_PERMISSIONS = {
    Role.CONSUMER: [
        "check_my_connection",
        "why_is_it_slow",
        "trace_path",
        "run_speedtest",
        "record_baseline",
        "compare_to_baseline",
        "clear_baseline",
    ],
    Role.OPERATOR: [
        # All consumer tools automatically included via hierarchy
        "list_devices",
        "get_device_status",
        "get_path",
        "diagnose_latency",
        "diagnose_from_here",
        "run_command",  # show commands only
        "detect_anomalies",
        "predict_trends",
        "get_collection_health",
        "get_config_history",
        "compare_configs",
        "explain_incident",
        "refresh_metrics",
    ],
    Role.ADMIN: [
        # All operator tools automatically included
        "start_agent",
        "stop_agent",
        "agent_status",
        "set_intent",
        "list_intents",
        "remove_intent",
        "get_incidents",
        "plan_goal",
        "execute_plan",
        "get_guardrail_status",
        "list_api_keys",
        "revoke_api_key",
    ],
    Role.SUPERUSER: [
        # All admin tools automatically included
        "create_api_key",
        "delete_api_key",
        "run_command",  # all commands including config
    ],
}


# Allowed command patterns by role
COMMAND_PATTERNS = {
    Role.OPERATOR: [
        r"^show\s+",
        r"^ping\s+",
        r"^traceroute\s+",
        r"^display\s+",  # Huawei
        r"^get\s+",      # Some vendors
    ],
    Role.SUPERUSER: [
        r".*",  # Everything (still logged)
    ],
}


class Authorizer:
    """Handles authorization checks for API keys."""

    def can_access_tool(self, key: APIKey, tool_name: str) -> bool:
        """Check if key has permission to access a tool.

        Args:
            key: API key
            tool_name: Name of the tool

        Returns:
            True if allowed, False otherwise
        """
        # Check explicit tool allowlist first
        if key.allowed_tools is not None:
            return tool_name in key.allowed_tools

        # Build full permission set including lower roles (hierarchical)
        allowed_tools = set()
        for role in Role:
            if role <= key.role:  # Include this role and all below
                allowed_tools.update(TOOL_PERMISSIONS.get(role, []))

        return tool_name in allowed_tools

    def can_access_device(self, key: APIKey, device_id: str) -> bool:
        """Check if key has permission to access a device.

        Args:
            key: API key
            device_id: Device identifier

        Returns:
            True if allowed, False otherwise
        """
        # Check explicit device allowlist
        if key.allowed_devices is not None:
            return device_id in key.allowed_devices

        # No restriction
        return True

    def can_run_command(self, key: APIKey, command: str) -> tuple[bool, Optional[str]]:
        """Check if key can run a specific command.

        Args:
            key: API key
            command: Command to check

        Returns:
            (allowed, reason_if_denied)
        """
        # Get allowed patterns for this role
        patterns = COMMAND_PATTERNS.get(key.role, [])

        if not patterns:
            return False, "Role has no command execution permissions"

        # Check if command matches any allowed pattern
        command_lower = command.strip().lower()
        for pattern in patterns:
            if re.match(pattern, command_lower):
                return True, None

        return False, "Command not allowed for this role (read-only commands only)"

    def get_allowed_tools(self, key: APIKey) -> list[str]:
        """Get list of all tools this key can access.

        Args:
            key: API key

        Returns:
            List of tool names
        """
        # Check explicit allowlist
        if key.allowed_tools is not None:
            return key.allowed_tools

        # Build hierarchical set
        allowed = set()
        for role in Role:
            if role <= key.role:
                allowed.update(TOOL_PERMISSIONS.get(role, []))

        return sorted(allowed)
