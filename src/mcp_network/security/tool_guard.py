"""
Tool-level security guard for MCP tool functions.

Defense-in-depth: enforces auth, authorization, input validation, and
audit logging inside every tool call regardless of transport (stdio or HTTP).
The HTTP middleware remains as the outer layer; this is the inner layer.
"""

import logging
import os
import time
from dataclasses import dataclass
from functools import wraps
from typing import Optional, Callable

from .auth import APIKey, Role
from .permissions import Authorizer, TOOL_PERMISSIONS
from .validation import InputValidator, ValidationError
from .audit import AuditLogger

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (from environment)
# ---------------------------------------------------------------------------

# stdio transport restriction: "consumer" (default) = consumer tools only,
# "full" = all tools allowed (for trusted local use).
_STDIO_MODE = os.getenv("MCP_NETWORK_STDIO_MODE", "consumer")

# Whether auth is required globally (mirrors the CLI --require-auth flag).
_REQUIRE_AUTH = os.getenv("MCP_NETWORK_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")

# Allow anonymous callers to use consumer tools even when auth is required.
_ALLOW_ANON_CONSUMER = os.getenv("MCP_NETWORK_ALLOW_ANON_CONSUMER", "").lower() in ("1", "true", "yes")


# Consumer tools that can work without authentication
CONSUMER_TOOLS = {
    "check_my_connection",
    "why_is_it_slow",
    "trace_path",
    "scan_local_network",
    "run_speedtest",
    "record_baseline",
    "compare_to_baseline",
    "clear_baseline",
}


# ---------------------------------------------------------------------------
# Singletons (lazy-init)
# ---------------------------------------------------------------------------

_authorizer: Optional[Authorizer] = None
_validator: Optional[InputValidator] = None
_audit_logger: Optional[AuditLogger] = None


def _get_authorizer() -> Authorizer:
    global _authorizer
    if _authorizer is None:
        _authorizer = Authorizer()
    return _authorizer


def _get_validator() -> InputValidator:
    global _validator
    if _validator is None:
        _validator = InputValidator()
    return _validator


def _get_audit_logger() -> Optional[AuditLogger]:
    """Return audit logger if audit logging is enabled."""
    global _audit_logger
    if _audit_logger is None:
        enable = os.getenv("MCP_NETWORK_ENABLE_AUDIT", "").lower() in ("1", "true", "yes")
        if enable:
            _audit_logger = AuditLogger()
    return _audit_logger


# ---------------------------------------------------------------------------
# CallerContext
# ---------------------------------------------------------------------------

@dataclass
class CallerContext:
    """Identity and transport information for the current caller."""
    api_key: Optional[APIKey]
    transport: str  # "http" or "stdio"
    client_ip: Optional[str] = None

    @property
    def is_authenticated(self) -> bool:
        return self.api_key is not None

    @property
    def role(self) -> Optional[Role]:
        return self.api_key.role if self.api_key else None


# ---------------------------------------------------------------------------
# Context extraction
# ---------------------------------------------------------------------------

def get_caller_context() -> CallerContext:
    """Extract caller identity from the current request context.

    For HTTP transport: reads api_key from scope["state"] set by AuthMiddleware.
    For stdio transport: returns unauthenticated context with transport="stdio".
    """
    try:
        from fastmcp.server.dependencies import get_http_request
        request = get_http_request()
        if request is not None:
            state = request.scope.get("state", {})
            api_key = state.get("api_key")
            # Best-effort client IP
            client_ip = None
            client = request.scope.get("client")
            if client:
                client_ip = client[0]
            return CallerContext(
                api_key=api_key,
                transport="http",
                client_ip=client_ip,
            )
    except (ImportError, RuntimeError, AttributeError):
        # No HTTP context available — we're on stdio or in a test
        pass

    return CallerContext(api_key=None, transport="stdio")


# ---------------------------------------------------------------------------
# Authorization helpers
# ---------------------------------------------------------------------------

def _check_tool_access(ctx: CallerContext, tool_name: str) -> Optional[str]:
    """Check if the caller can access this tool.

    Returns None if allowed, or an error message string if denied.
    """
    # --- stdio restrictions ---
    if ctx.transport == "stdio":
        if _STDIO_MODE == "consumer" and tool_name not in CONSUMER_TOOLS:
            return (
                f"Tool '{tool_name}' not available in consumer stdio mode. "
                "Set MCP_NETWORK_STDIO_MODE=full for unrestricted local access."
            )
        # In "full" mode, stdio has no restrictions
        return None

    # --- HTTP transport ---
    if ctx.api_key is not None:
        authorizer = _get_authorizer()
        if not authorizer.can_access_tool(ctx.api_key, tool_name):
            return f"Tool '{tool_name}' not allowed for role '{ctx.api_key.role.value}'"
        return None

    # Anonymous HTTP caller
    if not _REQUIRE_AUTH:
        return None  # auth not required — allow

    if _ALLOW_ANON_CONSUMER and tool_name in CONSUMER_TOOLS:
        return None  # anonymous consumer tools allowed

    return "Authentication required"


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------

def validate_params(tool_name: str, params: dict) -> dict:
    """Validate and sanitize tool parameters using InputValidator.

    Returns sanitized params dict. Raises ValidationError on failure.
    """
    validator = _get_validator()
    sanitized = {}

    for key, value in params.items():
        if not isinstance(value, str):
            sanitized[key] = value
            continue

        if key == "device_id":
            sanitized[key] = validator.validate_device_id(value)
        elif key in ("target", "destination", "host", "src", "dst"):
            sanitized[key] = validator.validate_destination(value)
        elif key == "command":
            sanitized[key] = validator.validate_command(value)
        elif key in ("intent", "goal"):
            sanitized[key] = validator.validate_intent(value)
        elif key == "interface":
            sanitized[key] = validator.validate_interface(value)
        elif key == "key_id":
            sanitized[key] = validator.validate_key_id(value)
        elif key == "port":
            sanitized[key] = validator.validate_port(value)
        elif key == "role":
            sanitized[key] = validator.validate_role(value)
        elif key in ("src_device", "dst_device"):
            sanitized[key] = validator.validate_device_id(value)
        elif key == "intent_id":
            sanitized[key] = validator.validate_key_id(value)
        else:
            sanitized[key] = value

    return sanitized


# ---------------------------------------------------------------------------
# Audit logging helper
# ---------------------------------------------------------------------------

def _audit_log(
    ctx: CallerContext,
    tool_name: str,
    params: dict,
    result: str,
    error: Optional[str] = None,
    duration_ms: Optional[float] = None,
):
    """Log a tool call to the audit log if enabled."""
    audit = _get_audit_logger()
    if audit is None:
        return
    audit.log_tool_call(
        key_id=ctx.api_key.key_id if ctx.api_key else None,
        role=ctx.api_key.role.value if ctx.api_key else None,
        tool=tool_name,
        params=params,
        result=result,
        error=error,
        duration_ms=duration_ms,
        client_ip=ctx.client_ip,
    )


# ---------------------------------------------------------------------------
# @guarded decorator
# ---------------------------------------------------------------------------

def guarded(min_role: Optional[Role] = None):
    """Decorator that enforces auth, authorization, validation, and audit on a tool.

    Args:
        min_role: Minimum role required. None means consumer-level (no role
                  needed if auth is not required).  Pass Role.OPERATOR,
                  Role.ADMIN, or Role.SUPERUSER for higher-privilege tools.
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            tool_name = fn.__name__
            start = time.time()

            # 1. Extract caller context
            ctx = get_caller_context()

            # 2. Check tool access (transport + role)
            denied = _check_tool_access(ctx, tool_name)
            if denied is None and min_role is not None and ctx.api_key is not None:
                # Additional role hierarchy check
                if ctx.api_key.role < min_role:
                    denied = f"Tool '{tool_name}' requires role '{min_role.value}' or higher"
            if denied is not None:
                _audit_log(ctx, tool_name, kwargs, "denied", error=denied)
                raise PermissionError(denied)

            # 3. Validate parameters
            try:
                sanitized = validate_params(tool_name, kwargs)
                kwargs.update(sanitized)
            except ValidationError as e:
                _audit_log(ctx, tool_name, kwargs, "error", error=str(e))
                raise

            # 4. Execute the tool
            try:
                result = await fn(*args, **kwargs)
                duration = (time.time() - start) * 1000
                _audit_log(ctx, tool_name, kwargs, "success", duration_ms=duration)
                return result
            except Exception as e:
                duration = (time.time() - start) * 1000
                _audit_log(ctx, tool_name, kwargs, "error", error=str(e), duration_ms=duration)
                raise

        return wrapper
    return decorator
