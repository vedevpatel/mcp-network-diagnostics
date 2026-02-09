"""Security middleware for MCP server integration."""

import time
from typing import Optional, Callable, Any
from functools import wraps

from .auth import AuthManager, APIKey
from .permissions import Authorizer
from .validation import InputValidator, ValidationError
from .ratelimit import CombinedRateLimiter
from .audit import AuditLogger


class SecurityContext:
    """Security context for a single request."""

    def __init__(
        self,
        api_key: Optional[APIKey] = None,
        client_ip: Optional[str] = None,
        tool_name: Optional[str] = None,
    ):
        self.api_key = api_key
        self.client_ip = client_ip
        self.tool_name = tool_name
        self.start_time = time.time()

    def get_duration_ms(self) -> float:
        """Get request duration in milliseconds."""
        return (time.time() - self.start_time) * 1000


class SecurityMiddleware:
    """Middleware that enforces security policies on MCP tool calls."""

    def __init__(
        self,
        auth_manager: AuthManager,
        require_auth: bool = True,
        allow_anonymous_consumer: bool = False,
        enable_rate_limiting: bool = True,
        global_rate_limit: int = 1000,
        enable_audit_logging: bool = True,
        audit_log_dir: Optional[str] = None,
    ):
        """Initialize security middleware.

        Args:
            auth_manager: API key authentication manager
            require_auth: Whether to require authentication
            allow_anonymous_consumer: Allow unauthenticated consumer tools
            enable_rate_limiting: Enable rate limiting
            global_rate_limit: Global requests per minute limit
            enable_audit_logging: Enable audit logging
            audit_log_dir: Directory for audit logs
        """
        self.auth_manager = auth_manager
        self.authorizer = Authorizer()
        self.validator = InputValidator()
        self.rate_limiter = CombinedRateLimiter(global_rate_limit) if enable_rate_limiting else None
        self.audit_logger = AuditLogger(audit_log_dir) if enable_audit_logging else None

        self.require_auth = require_auth
        self.allow_anonymous_consumer = allow_anonymous_consumer
        self.enable_rate_limiting = enable_rate_limiting
        self.enable_audit_logging = enable_audit_logging

        # Consumer tools that can work without authentication
        self.consumer_tools = {
            "check_my_connection",
            "why_is_it_slow",
            "trace_path",
            "run_speedtest",
            "record_baseline",
            "compare_to_baseline",
            "clear_baseline",
        }

    def authenticate(self, api_key_header: Optional[str]) -> Optional[APIKey]:
        """Authenticate request using API key.

        Args:
            api_key_header: API key from Authorization header

        Returns:
            APIKey object if authenticated, None otherwise
        """
        if not api_key_header:
            return None

        # Support both "Bearer <key>" and raw key
        if api_key_header.startswith("Bearer "):
            api_key_header = api_key_header[7:]

        return self.auth_manager.authenticate(api_key_header)

    def check_authorization(
        self,
        api_key: Optional[APIKey],
        tool_name: str,
        params: dict,
    ) -> tuple[bool, Optional[str]]:
        """Check if request is authorized.

        Args:
            api_key: Authenticated API key (or None)
            tool_name: Tool being called
            params: Tool parameters

        Returns:
            (authorized, error_message)
        """
        # Check if authentication is required
        if not api_key:
            if not self.require_auth:
                return True, None
            if self.allow_anonymous_consumer and tool_name in self.consumer_tools:
                return True, None
            return False, "Authentication required"

        # Check tool access
        if not self.authorizer.can_access_tool(api_key, tool_name):
            return False, f"Tool '{tool_name}' not allowed for role '{api_key.role.value}'"

        # Check device access (if device_id parameter present)
        device_id = params.get("device_id")
        if device_id:
            if not self.authorizer.can_access_device(api_key, device_id):
                return False, f"Device '{device_id}' not allowed for this key"

        # Check command access (if command parameter present)
        command = params.get("command")
        if command and tool_name == "run_command":
            allowed, reason = self.authorizer.can_run_command(api_key, command)
            if not allowed:
                return False, reason

        return True, None

    def check_rate_limit(
        self,
        api_key: Optional[APIKey],
    ) -> tuple[bool, Optional[str], float]:
        """Check rate limits.

        Args:
            api_key: Authenticated API key

        Returns:
            (allowed, error_message, retry_after_seconds)
        """
        if not self.enable_rate_limiting or not self.rate_limiter:
            return True, None, 0.0

        if not api_key:
            # Anonymous requests get minimal rate limit
            key_id = "__anonymous__"
            key_limit = 10  # 10/min for anonymous
        else:
            key_id = api_key.key_id
            key_limit = api_key.rate_limit

        allowed, reason, retry_after = self.rate_limiter.check(key_id, key_limit)

        if not allowed:
            return False, reason, retry_after

        return True, None, 0.0

    def validate_parameters(self, tool_name: str, params: dict) -> dict:
        """Validate and sanitize tool parameters.

        Args:
            tool_name: Tool being called
            params: Tool parameters

        Returns:
            Sanitized parameters

        Raises:
            ValidationError: If validation fails
        """
        sanitized = {}

        for key, value in params.items():
            if not isinstance(value, str):
                # Non-string parameters pass through
                sanitized[key] = value
                continue

            # Apply validation based on parameter name
            if key == "device_id":
                sanitized[key] = self.validator.validate_device_id(value)
            elif key in ("target", "destination", "host", "src", "dst"):
                sanitized[key] = self.validator.validate_destination(value)
            elif key == "command":
                sanitized[key] = self.validator.validate_command(value)
            elif key in ("intent", "goal"):
                sanitized[key] = self.validator.validate_intent(value)
            elif key == "interface":
                sanitized[key] = self.validator.validate_interface(value)
            elif key == "key_id":
                sanitized[key] = self.validator.validate_key_id(value)
            elif key == "port":
                sanitized[key] = self.validator.validate_port(value)
            elif key == "role":
                sanitized[key] = self.validator.validate_role(value)
            else:
                # Unknown parameter - just sanitize for output
                sanitized[key] = value

        return sanitized

    def log_request(
        self,
        context: SecurityContext,
        params: dict,
        result: str,
        error: Optional[str] = None,
    ):
        """Log request to audit log.

        Args:
            context: Security context
            params: Tool parameters
            result: Result status
            error: Error message if any
        """
        if not self.enable_audit_logging or not self.audit_logger:
            return

        self.audit_logger.log_tool_call(
            key_id=context.api_key.key_id if context.api_key else None,
            role=context.api_key.role.value if context.api_key else None,
            tool=context.tool_name,
            params=params,
            result=result,
            error=error,
            duration_ms=context.get_duration_ms(),
            client_ip=context.client_ip,
        )

    def log_auth_failure(
        self,
        key_id: Optional[str],
        error: str,
        client_ip: Optional[str] = None,
    ):
        """Log authentication failure.

        Args:
            key_id: Attempted key ID
            error: Error message
            client_ip: Client IP address
        """
        if not self.enable_audit_logging or not self.audit_logger:
            return

        self.audit_logger.log_auth(
            key_id=key_id,
            role=None,
            result="denied",
            error=error,
            client_ip=client_ip,
        )

    def log_rate_limit(
        self,
        api_key: Optional[APIKey],
        reason: str,
        retry_after: float,
        client_ip: Optional[str] = None,
    ):
        """Log rate limit event.

        Args:
            api_key: API key (if authenticated)
            reason: Rate limit reason
            retry_after: Seconds until retry allowed
            client_ip: Client IP address
        """
        if not self.enable_audit_logging or not self.audit_logger:
            return

        self.audit_logger.log_rate_limit(
            key_id=api_key.key_id if api_key else "__anonymous__",
            reason=reason,
            retry_after=retry_after,
            client_ip=client_ip,
        )

    def secure_tool(self, tool_func: Callable) -> Callable:
        """Decorator to secure an MCP tool with authentication, authorization, validation.

        Args:
            tool_func: MCP tool function to secure

        Returns:
            Secured tool function
        """
        @wraps(tool_func)
        async def wrapper(*args, **kwargs):
            # Extract tool name
            tool_name = tool_func.__name__

            # Create security context
            # Note: In real implementation, would extract API key and client IP from request
            context = SecurityContext(
                api_key=None,  # Would be extracted from Authorization header
                client_ip=None,  # Would be extracted from request
                tool_name=tool_name,
            )

            try:
                # 1. Authenticate
                # In real implementation: api_key_header = request.headers.get("Authorization")
                # context.api_key = self.authenticate(api_key_header)

                # 2. Check rate limits
                allowed, error, retry_after = self.check_rate_limit(context.api_key)
                if not allowed:
                    self.log_rate_limit(context.api_key, error, retry_after, context.client_ip)
                    raise PermissionError(f"Rate limit exceeded: {error}. Retry after {retry_after:.0f}s")

                # 3. Validate parameters
                params = kwargs.copy()
                try:
                    params = self.validate_parameters(tool_name, params)
                    kwargs.update(params)
                except ValidationError as e:
                    self.log_request(context, params, "error", str(e))
                    raise

                # 4. Check authorization
                authorized, auth_error = self.check_authorization(context.api_key, tool_name, params)
                if not authorized:
                    if not context.api_key:
                        self.log_auth_failure(None, auth_error, context.client_ip)
                    self.log_request(context, params, "denied", auth_error)
                    raise PermissionError(auth_error)

                # 5. Execute tool
                result = await tool_func(*args, **kwargs)

                # 6. Log success
                self.log_request(context, params, "success")

                return result

            except Exception as e:
                # Log error
                self.log_request(context, kwargs, "error", str(e))
                raise

        return wrapper


def create_security_middleware(
    require_auth: bool = True,
    allow_anonymous_consumer: bool = False,
    api_keys_file: Optional[str] = None,
    enable_rate_limiting: bool = True,
    global_rate_limit: int = 1000,
    enable_audit_logging: bool = True,
    audit_log_dir: Optional[str] = None,
) -> SecurityMiddleware:
    """Factory function to create security middleware.

    Args:
        require_auth: Require authentication for all requests
        allow_anonymous_consumer: Allow unauthenticated consumer tool access
        api_keys_file: Path to API keys file
        enable_rate_limiting: Enable rate limiting
        global_rate_limit: Global requests per minute limit
        enable_audit_logging: Enable audit logging
        audit_log_dir: Directory for audit logs

    Returns:
        Configured SecurityMiddleware instance
    """
    auth_manager = AuthManager(api_keys_file)

    return SecurityMiddleware(
        auth_manager=auth_manager,
        require_auth=require_auth,
        allow_anonymous_consumer=allow_anonymous_consumer,
        enable_rate_limiting=enable_rate_limiting,
        global_rate_limit=global_rate_limit,
        enable_audit_logging=enable_audit_logging,
        audit_log_dir=audit_log_dir,
    )
