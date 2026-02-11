"""
HTTP (StreamableHTTP) transport for MCP with auth and rate limiting.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _get_auth_manager(api_keys_file: Optional[str] = None):
    from mcp_network.security import AuthManager
    if api_keys_file:
        return AuthManager(api_keys_file)
    return AuthManager(str(Path.home() / ".mcp_network" / "api_keys.json"))


def _get_authorizer():
    from mcp_network.security import Authorizer
    return Authorizer()


def _get_rate_limiter():
    from mcp_network.security import CombinedRateLimiter
    return CombinedRateLimiter(global_limit=int(os.getenv("MCP_NETWORK_GLOBAL_RPM", "1000")))


def _extract_bearer(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header or not auth_header.strip().lower().startswith("bearer "):
        return None
    return auth_header.strip()[7:].strip()


class AuthMiddleware:
    """Starlette middleware: validate API key, set request.state.api_key, return 401 if required and invalid."""

    def __init__(self, app, require_auth: bool, api_keys_file: Optional[str] = None):
        self.app = app
        self.require_auth = require_auth
        self.auth_manager = _get_auth_manager(api_keys_file)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.requests import Request

        request = Request(scope)
        auth_header = request.headers.get("Authorization")
        key_str = _extract_bearer(auth_header)
        api_key = self.auth_manager.authenticate(key_str) if key_str else None

        if api_key is None and self.require_auth:
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [[b"content-type", b"application/json"], [b"www-authenticate", b'Bearer realm="MCP"']],
            })
            await send({
                "type": "http.response.body",
                "body": json.dumps({"error": "unauthorized", "message": "Valid API key required"}).encode(),
            })
            return

        scope["state"] = scope.get("state", {})
        scope["state"]["api_key"] = api_key
        # Operator/admin: scope storage and tools to this key's tenant
        if api_key is not None:
            from mcp_network.security import Role
            from mcp_network.storage.tenant import set_tenant_id
            if api_key.role in (Role.OPERATOR, Role.ADMIN, Role.SUPERUSER):
                set_tenant_id(api_key.tenant_id or api_key.key_id)
        await self.app(scope, receive, send)


class RateLimitMiddleware:
    """Starlette middleware: per-key and global rate limit, return 429 when exceeded.

    NOTE: The in-memory rate limiter is acceptable for single-process
    deployments.  Multi-process deployments need a Redis-backed rate limiter.
    """

    def __init__(self, app, api_keys_file: Optional[str] = None):
        self.app = app
        self.rate_limiter = _get_rate_limiter()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = scope.get("state", {})
        api_key = state.get("api_key")
        key_id = api_key.key_id if api_key else "__anonymous__"
        limit = api_key.rate_limit if api_key else 10

        allowed, reason, retry_after = self.rate_limiter.check(key_id, limit)
        if not allowed:
            body = json.dumps({
                "error": "rate_limit_exceeded",
                "message": reason or "Too many requests",
                "retry_after": int(retry_after),
            }).encode()
            await send({"type": "http.response.start", "status": 429, "headers": [[b"content-type", b"application/json"], [b"retry-after", str(int(retry_after)).encode()]]})
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)


class AuthzMiddleware:
    """Starlette middleware: for MCP tools/call, check api_key can access tool name; return 403 if not."""

    def __init__(self, app, require_auth: bool):
        self.app = app
        self.require_auth = require_auth
        self.authorizer = _get_authorizer()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Only inspect MCP path (e.g. /mcp) POST body for tools/call
        path = scope.get("path", "")
        if scope["method"] != "POST" or not path.rstrip("/").endswith("/mcp"):
            await self.app(scope, receive, send)
            return

        # Read body (we need to replay it for the next handler)
        MAX_BODY_SIZE = 1_048_576  # 1 MB
        body = b""
        more = True
        while more:
            event = await receive()
            if event["type"] == "http.request":
                body += event.get("body", b"")
                if len(body) > MAX_BODY_SIZE:
                    await _send_json(send, 413, {
                        "error": "payload_too_large",
                        "message": f"Request body exceeds {MAX_BODY_SIZE} bytes",
                    })
                    return
                more = event.get("more_body", False)

        state = scope.get("state", {})
        api_key = state.get("api_key")

        if body:
            try:
                data = json.loads(body.decode())
                if data.get("method") == "tools/call":
                    params = data.get("params") or {}
                    tool_name = params.get("name")
                    if tool_name:
                        if api_key is None and self.require_auth:
                            await _send_json(send, 403, {"error": "forbidden", "message": "Authentication required"})
                            return
                        if api_key is not None:
                            if not self.authorizer.can_access_tool(api_key, tool_name):
                                await _send_json(send, 403, {"error": "forbidden", "message": f"Tool '{tool_name}' not allowed for your role"})
                                return
            except (json.JSONDecodeError, KeyError):
                # If auth is required, reject malformed JSON bodies
                # instead of silently passing them through
                if self.require_auth:
                    await _send_json(send, 400, {
                        "error": "bad_request",
                        "message": "Malformed JSON-RPC body",
                    })
                    return

        # Replay request body for downstream (they read via receive())
        async def replay_receive():
            return {"type": "http.request", "body": body, "more_body": False}

        await self.app(scope, replay_receive, send)


class CORSMiddleware:
    """Restrictive CORS: same-origin by default, configurable via env."""

    def __init__(self, app):
        self.app = app
        raw = os.getenv("MCP_NETWORK_CORS_ORIGINS", "")
        self.allowed_origins = {o.strip() for o in raw.split(",") if o.strip()} if raw else set()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Handle preflight
        headers_raw = dict(scope.get("headers", []))
        origin = headers_raw.get(b"origin", b"").decode()

        if scope["method"] == "OPTIONS":
            cors_headers = self._cors_headers(origin)
            await send({
                "type": "http.response.start",
                "status": 204,
                "headers": cors_headers,
            })
            await send({"type": "http.response.body", "body": b""})
            return

        # Wrap send to inject CORS headers
        cors_headers = self._cors_headers(origin)

        async def send_with_cors(message):
            if message["type"] == "http.response.start":
                existing = list(message.get("headers", []))
                existing.extend(cors_headers)
                message = {**message, "headers": existing}
            await send(message)

        await self.app(scope, receive, send_with_cors)

    def _cors_headers(self, origin: str) -> list:
        headers = []
        if origin and (origin in self.allowed_origins or not self.allowed_origins):
            # If no origins configured, only same-origin requests pass (browser default)
            if self.allowed_origins:
                headers.append([b"access-control-allow-origin", origin.encode()])
                headers.append([b"access-control-allow-methods", b"GET, POST, OPTIONS"])
                headers.append([b"access-control-allow-headers", b"Authorization, Content-Type, X-API-Key"])
                headers.append([b"access-control-max-age", b"3600"])
        return headers


async def _send_json(send, status: int, obj: dict):
    body_bytes = json.dumps(obj).encode()
    await send({"type": "http.response.start", "status": status, "headers": [[b"content-type", b"application/json"]]})
    await send({"type": "http.response.body", "body": body_bytes})


def run_http(
    host: str = "0.0.0.0",
    port: int = 8000,
    path: str = "/mcp",
    require_auth: bool = False,
    api_keys_file: Optional[str] = None,
):
    """Create StreamableHTTP ASGI app with auth/rate-limit middleware and run uvicorn."""
    try:
        from fastmcp.server.http import create_streamable_http_app
    except ImportError:
        try:
            from mcp.server.http import create_streamable_http_app
        except ImportError:
            if require_auth:
                raise RuntimeError(
                    "create_streamable_http_app not available but require_auth=True. "
                    "Cannot run HTTP transport without auth middleware. "
                    "Install fastmcp or mcp with HTTP support."
                )
            # Fallback: use mcp.run() without custom middleware (no auth)
            logger.warning("create_streamable_http_app not found; running with mcp.run(transport=streamable-http) without middleware")
            from mcp_network.app import mcp
            mcp.run(transport="streamable-http", host=host, port=port, path=path)
            return

    from mcp_network.app import mcp

    base_app = create_streamable_http_app(
        mcp,
        streamable_http_path=path.rstrip("/") or "/mcp",
        auth=None,
        middleware=None,
    )

    # Wrap with our middleware (inner to outer: base_app -> Authz -> RateLimit -> Auth -> CORS)
    app = base_app
    app = AuthzMiddleware(app, require_auth)
    app = RateLimitMiddleware(app)
    app = AuthMiddleware(app, require_auth, api_keys_file)
    app = CORSMiddleware(app)

    import uvicorn
    logger.info(f"Starting MCP HTTP server at http://{host}:{port}{path} (require_auth={require_auth})")
    uvicorn.run(app, host=host, port=port)
