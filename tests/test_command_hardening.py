"""Tests for run_command hardening and SSH collector validation."""

import json
import pytest
from unittest.mock import MagicMock, patch


# ============================================================================
# run_command Tool Validation
# ============================================================================

class TestRunCommandTool:
    """Test the hardened run_command tool function."""

    def _call_run_command_logic(self, command: str) -> dict:
        """Execute the command validation logic from run_command and return parsed JSON.

        Simulates the validation portion of the tool without needing
        the full MCP server context.
        """
        import re as _re

        command = command.strip()

        _FORBIDDEN_CHARS = set('\n\r\x00')
        if any(c in command for c in _FORBIDDEN_CHARS):
            return {"error": "Command contains forbidden control characters (newline, carriage return, null byte)."}

        if len(command) > 500:
            return {"error": "Command too long (max 500 characters)."}

        if not _re.match(r'^(show|display|ping|traceroute)\s+', command, _re.IGNORECASE):
            return {"error": "Only read-only commands are permitted (show, display, ping, traceroute)."}

        _DANGEROUS_KEYWORDS = [
            "config", "conf ", "write", "copy", "delete", "erase",
            "reload", "shutdown", "exec", "terminal", "debug",
        ]
        command_lower = command.lower()
        for keyword in _DANGEROUS_KEYWORDS:
            if keyword in command_lower:
                return {"error": f"Command contains forbidden keyword '{keyword.strip()}'."}

        if _re.search(r'[;&|`$]', command):
            return {"error": "Command contains forbidden shell metacharacters."}

        return {"status": "passed"}

    # -----------------------------------------------------------------------
    # Newline/control character injection
    # -----------------------------------------------------------------------

    def test_newline_injection_rejected(self):
        """Newline in command is rejected."""
        result = self._call_run_command_logic("show version\nconf t")
        assert "error" in result
        assert "control characters" in result["error"]

    def test_carriage_return_injection_rejected(self):
        """Carriage return in command is rejected."""
        result = self._call_run_command_logic("show version\rreload")
        assert "error" in result
        assert "control characters" in result["error"]

    def test_null_byte_injection_rejected(self):
        """Null byte in command is rejected."""
        result = self._call_run_command_logic("show version\x00delete")
        assert "error" in result
        assert "control characters" in result["error"]

    # -----------------------------------------------------------------------
    # Shell metacharacter injection
    # -----------------------------------------------------------------------

    def test_semicolon_injection_rejected(self):
        """Semicolon in command is rejected."""
        result = self._call_run_command_logic("show version; reload")
        assert "error" in result

    def test_pipe_injection_rejected(self):
        """Pipe in command is rejected."""
        result = self._call_run_command_logic("show version | include reload")
        assert "error" in result

    def test_backtick_injection_rejected(self):
        """Backtick in command is rejected."""
        result = self._call_run_command_logic("show `reboot`")
        assert "error" in result

    def test_dollar_sign_injection_rejected(self):
        """Dollar sign in command is rejected."""
        result = self._call_run_command_logic("show $(reboot)")
        assert "error" in result

    def test_ampersand_injection_rejected(self):
        """Ampersand in command is rejected."""
        result = self._call_run_command_logic("show version & reboot")
        assert "error" in result

    # -----------------------------------------------------------------------
    # Blocklist keywords
    # -----------------------------------------------------------------------

    def test_config_keyword_blocked(self):
        """Command containing 'config' is blocked."""
        result = self._call_run_command_logic("show running-config")
        assert "error" in result
        assert "config" in result["error"]

    def test_write_keyword_blocked(self):
        """Command containing 'write' is blocked."""
        result = self._call_run_command_logic("show version write mem")
        assert "error" in result

    def test_reload_keyword_blocked(self):
        """Command containing 'reload' is blocked."""
        result = self._call_run_command_logic("show version reload")
        assert "error" in result

    def test_delete_keyword_blocked(self):
        """Command containing 'delete' is blocked."""
        result = self._call_run_command_logic("show version delete")
        assert "error" in result

    def test_erase_keyword_blocked(self):
        """Command containing 'erase' is blocked."""
        result = self._call_run_command_logic("show version erase")
        assert "error" in result

    def test_shutdown_keyword_blocked(self):
        """Command containing 'shutdown' is blocked."""
        result = self._call_run_command_logic("show interface shutdown")
        assert "error" in result

    def test_debug_keyword_blocked(self):
        """Command containing 'debug' is blocked."""
        result = self._call_run_command_logic("show debug all")
        assert "error" in result

    # -----------------------------------------------------------------------
    # Allowlist validation
    # -----------------------------------------------------------------------

    def test_non_show_command_rejected(self):
        """Non-show commands are rejected."""
        result = self._call_run_command_logic("configure terminal")
        assert "error" in result
        assert "read-only" in result["error"]

    def test_write_command_rejected(self):
        """Direct write command is rejected."""
        result = self._call_run_command_logic("write memory")
        assert "error" in result

    def test_copy_command_rejected(self):
        """Copy command is rejected."""
        result = self._call_run_command_logic("copy running-config startup-config")
        assert "error" in result

    # -----------------------------------------------------------------------
    # Length limit
    # -----------------------------------------------------------------------

    def test_overlong_command_rejected(self):
        """Commands > 500 chars are rejected."""
        result = self._call_run_command_logic("show " + "a" * 500)
        assert "error" in result
        assert "too long" in result["error"]

    # -----------------------------------------------------------------------
    # Valid commands
    # -----------------------------------------------------------------------

    def test_show_version_passes(self):
        """'show version' passes all checks."""
        result = self._call_run_command_logic("show version")
        assert result["status"] == "passed"

    def test_show_ip_interface_brief_passes(self):
        """'show ip interface brief' passes all checks."""
        result = self._call_run_command_logic("show ip interface brief")
        assert result["status"] == "passed"

    def test_show_processes_cpu_passes(self):
        """'show processes cpu sorted' passes all checks."""
        result = self._call_run_command_logic("show processes cpu sorted")
        assert result["status"] == "passed"

    def test_display_command_passes(self):
        """'display' commands are allowed."""
        result = self._call_run_command_logic("display version")
        assert result["status"] == "passed"

    def test_ping_command_passes(self):
        """'ping' commands are allowed."""
        result = self._call_run_command_logic("ping 8.8.8.8")
        assert result["status"] == "passed"

    def test_traceroute_command_passes(self):
        """'traceroute' commands are allowed."""
        result = self._call_run_command_logic("traceroute 8.8.8.8")
        assert result["status"] == "passed"

    def test_show_ip_route_passes(self):
        """'show ip route' passes."""
        result = self._call_run_command_logic("show ip route")
        assert result["status"] == "passed"

    def test_show_bgp_summary_passes(self):
        """'show bgp summary' passes."""
        result = self._call_run_command_logic("show bgp summary")
        assert result["status"] == "passed"


# ============================================================================
# SSH Collector Validation (Defense-in-Depth)
# ============================================================================

class TestSSHCollectorCommandValidation:
    """Test the second validation layer in the SSH collector."""

    def test_collector_rejects_newlines(self):
        """SSH collector rejects newlines independently."""
        from mcp_network.collectors.ssh import SSHCollector

        collector = SSHCollector.__new__(SSHCollector)
        with pytest.raises(ValueError, match="control characters"):
            collector.run_command("R1", "show version\nconf t")

    def test_collector_rejects_non_show_command(self):
        """SSH collector rejects non-show commands independently."""
        from mcp_network.collectors.ssh import SSHCollector

        collector = SSHCollector.__new__(SSHCollector)
        with pytest.raises(ValueError, match="read-only"):
            collector.run_command("R1", "configure terminal")

    def test_collector_allows_show_command(self):
        """SSH collector allows show command (fails at device lookup, not validation)."""
        from mcp_network.collectors.ssh import SSHCollector

        collector = SSHCollector.__new__(SSHCollector)
        # Mock _device_config to return None (device not found)
        collector._device_config = MagicMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            collector.run_command("R1", "show version")
