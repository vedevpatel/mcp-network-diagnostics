"""Tests for tool-level security guard (tool_guard.py)."""

import asyncio
import time
import pytest
from unittest.mock import patch, MagicMock

from mcp_network.security.auth import APIKey, Role
from mcp_network.security.validation import ValidationError
from mcp_network.security.tool_guard import (
    CallerContext,
    get_caller_context,
    guarded,
    validate_params,
    CONSUMER_TOOLS,
    _check_tool_access,
)


# ============================================================================
# CallerContext
# ============================================================================

class TestCallerContext:
    """Test CallerContext dataclass behavior."""

    def test_authenticated_context(self):
        """Authenticated context has api_key and role."""
        key = APIKey(
            key_id="test123",
            key_hash="fake",
            role=Role.OPERATOR,
            created_at=time.time(),
            description="test",
        )
        ctx = CallerContext(api_key=key, transport="http", client_ip="1.2.3.4")
        assert ctx.is_authenticated is True
        assert ctx.role == Role.OPERATOR
        assert ctx.client_ip == "1.2.3.4"

    def test_anonymous_context(self):
        """Anonymous context has no api_key or role."""
        ctx = CallerContext(api_key=None, transport="stdio")
        assert ctx.is_authenticated is False
        assert ctx.role is None


# ============================================================================
# Context Extraction
# ============================================================================

class TestGetCallerContext:
    """Test context extraction from different transports."""

    def test_stdio_context_when_no_http_request(self):
        """When no HTTP request is available, returns stdio context."""
        # By default in a test, there's no fastmcp context
        ctx = get_caller_context()
        assert ctx.transport == "stdio"
        assert ctx.api_key is None

    def test_http_context_extraction(self):
        """HTTP context extraction reads api_key from request scope."""
        key = APIKey(
            key_id="http_key",
            key_hash="fake",
            role=Role.ADMIN,
            created_at=time.time(),
            description="http test",
        )
        mock_request = MagicMock()
        mock_request.scope = {
            "state": {"api_key": key},
            "client": ("192.168.1.1", 12345),
        }

        with patch("mcp_network.security.tool_guard.get_http_request", return_value=mock_request, create=True):
            # Need to re-import or patch properly
            from mcp_network.security import tool_guard
            try:
                # from fastmcp.server.dependencies import get_http_request
                # original = get_http_request
                pass
            except ImportError:
                pass

            # Simulate the import working
            with patch.dict("sys.modules", {
                "fastmcp": MagicMock(),
                "fastmcp.server": MagicMock(),
                "fastmcp.server.dependencies": MagicMock(get_http_request=lambda: mock_request),
            }):
                # Force reimport
                import importlib
                importlib.reload(tool_guard)
                ctx = tool_guard.get_caller_context()
                assert ctx.transport == "http"
                assert ctx.api_key == key
                assert ctx.client_ip == "192.168.1.1"


# ============================================================================
# Tool Access Checks
# ============================================================================

class TestToolAccess:
    """Test _check_tool_access for different transports and roles."""

    def test_stdio_consumer_mode_allows_consumer_tools(self, monkeypatch):
        """Consumer stdio mode allows consumer tools."""
        import mcp_network.security.tool_guard as tg
        monkeypatch.setattr(tg, "_STDIO_MODE", "consumer")
        ctx = CallerContext(api_key=None, transport="stdio")
        result = _check_tool_access(ctx, "check_my_connection")
        assert result is None

    def test_stdio_consumer_mode_blocks_operator_tools(self, monkeypatch):
        """Consumer stdio mode blocks operator tools."""
        import mcp_network.security.tool_guard as tg
        monkeypatch.setattr(tg, "_STDIO_MODE", "consumer")
        ctx = CallerContext(api_key=None, transport="stdio")
        result = _check_tool_access(ctx, "run_command")
        assert result is not None
        assert "not available" in result

    def test_http_authenticated_operator_can_access_operator_tool(self):
        """HTTP operator can access operator-level tools."""
        key = APIKey(
            key_id="op1",
            key_hash="fake",
            role=Role.OPERATOR,
            created_at=time.time(),
            description="op",
        )
        ctx = CallerContext(api_key=key, transport="http")
        result = _check_tool_access(ctx, "list_devices")
        assert result is None

    def test_http_anonymous_without_require_auth(self):
        """Anonymous HTTP caller passes when auth not required."""
        ctx = CallerContext(api_key=None, transport="http")
        with patch("mcp_network.security.tool_guard._REQUIRE_AUTH", False):
            result = _check_tool_access(ctx, "list_devices")
            assert result is None

    def test_http_anonymous_with_require_auth(self):
        """Anonymous HTTP caller blocked when auth required."""
        ctx = CallerContext(api_key=None, transport="http")
        with patch("mcp_network.security.tool_guard._REQUIRE_AUTH", True):
            with patch("mcp_network.security.tool_guard._ALLOW_ANON_CONSUMER", False):
                result = _check_tool_access(ctx, "list_devices")
                assert result is not None
                assert "Authentication required" in result


# ============================================================================
# Parameter Validation
# ============================================================================

class TestParameterValidation:
    """Test validate_params catches injection patterns."""

    def test_valid_device_id(self):
        """Valid device IDs pass validation."""
        result = validate_params("test_tool", {"device_id": "R1"})
        assert result["device_id"] == "R1"

    def test_injection_in_device_id(self):
        """Shell metacharacters in device_id raise ValidationError."""
        with pytest.raises(ValidationError):
            validate_params("test_tool", {"device_id": "R1; rm -rf /"})

    def test_valid_destination(self):
        """Valid hostnames pass validation."""
        result = validate_params("test_tool", {"destination": "8.8.8.8"})
        assert result["destination"] == "8.8.8.8"

    def test_injection_in_destination(self):
        """Injection in destination raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_params("test_tool", {"destination": "8.8.8.8; cat /etc/passwd"})

    def test_valid_command(self):
        """Valid show commands pass validation."""
        result = validate_params("test_tool", {"command": "show version"})
        assert result["command"] == "show version"

    def test_injection_in_command(self):
        """Shell injection in command raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_params("test_tool", {"command": "show version; reload"})

    def test_intent_validation(self):
        """Intent field gets validated."""
        result = validate_params("test_tool", {"intent": "keep latency below 50ms"})
        assert "latency" in result["intent"]

    def test_non_string_params_pass_through(self):
        """Non-string params pass through without validation."""
        result = validate_params("test_tool", {"limit": 10, "hours": 24})
        assert result["limit"] == 10
        assert result["hours"] == 24


# ============================================================================
# @guarded Decorator
# ============================================================================

class TestGuardedDecorator:
    """Test the @guarded decorator end-to-end."""

    def test_consumer_tool_allows_stdio(self):
        """Consumer tool works on stdio transport."""
        @guarded()
        async def check_my_connection():
            return "ok"

        result = asyncio.run(check_my_connection())
        assert result == "ok"

    def test_operator_tool_blocks_on_consumer_stdio(self, monkeypatch):
        """Operator tool blocked in consumer stdio mode."""
        monkeypatch.setattr("mcp_network.security.tool_guard._STDIO_MODE", "consumer")

        @guarded(min_role=Role.OPERATOR)
        async def run_command(device_id="R1", command="show version"):
            return "output"

        with pytest.raises(PermissionError, match="not available"):
            asyncio.run(run_command(device_id="R1", command="show version"))

    def test_admin_tool_blocks_on_consumer_stdio(self, monkeypatch):
        """Admin tool blocked in consumer stdio mode."""
        monkeypatch.setattr("mcp_network.security.tool_guard._STDIO_MODE", "consumer")

        @guarded(min_role=Role.ADMIN)
        async def start_agent(poll_interval_seconds=60):
            return "started"

        with pytest.raises(PermissionError, match="not available"):
            asyncio.run(start_agent(poll_interval_seconds=60))

    def test_decorator_validates_params(self):
        """Guard decorator runs parameter validation."""
        @guarded()
        async def why_is_it_slow(destination="8.8.8.8"):
            return "slow"

        # Valid
        result = asyncio.run(why_is_it_slow(destination="8.8.8.8"))
        assert result == "slow"

    def test_decorator_rejects_injection_params(self):
        """Guard decorator rejects injection in params."""
        @guarded()
        async def why_is_it_slow(destination="8.8.8.8"):
            return "slow"

        with pytest.raises(ValidationError):
            asyncio.run(why_is_it_slow(destination="`cat /etc/passwd`"))

    def test_consumer_tools_set_matches_permissions(self):
        """CONSUMER_TOOLS set matches TOOL_PERMISSIONS for consumer role."""
        from mcp_network.security.permissions import TOOL_PERMISSIONS
        assert CONSUMER_TOOLS == set(TOOL_PERMISSIONS[Role.CONSUMER])
