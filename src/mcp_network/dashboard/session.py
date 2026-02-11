"""
Consumer session: signed cookie-based identity for dashboard (guest or future sign-in).
Exposes consumer_identity on request.state for tenant scoping and quotas.
"""

import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Cookie name and expiry (90 days for guest)
SESSION_COOKIE_NAME = "mcp_consumer_session"
SESSION_EXPIRY_DAYS = 90
SESSION_ID_BYTES = 32

# Set to True once we have warned about the default secret
_default_secret_warned = False


def _get_secret() -> bytes:
    """Session signing secret from env.

    In production (non-localhost), MCP_NETWORK_SESSION_SECRET **must** be set.
    For local-only development a randomly generated per-process fallback is
    used and a loud warning is emitted on first use.
    """
    global _default_secret_warned
    raw = os.getenv("MCP_NETWORK_SESSION_SECRET", "").strip().encode()
    if raw:
        return hashlib.sha256(raw).digest()

    # No secret configured — check whether we should refuse to start.
    bind_host = os.getenv("MCP_NETWORK_DASHBOARD_HOST", "127.0.0.1")
    if bind_host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(
            "SECURITY: MCP_NETWORK_SESSION_SECRET environment variable is required "
            "when the dashboard listens on a non-localhost interface. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    # Local development: generate a random per-process secret so forging is
    # not possible from source code alone.  Warn once.
    if not _default_secret_warned:
        logger.warning(
            "MCP_NETWORK_SESSION_SECRET is not set — using a random per-process "
            "secret. Sessions will not survive restarts. Set the env var in production."
        )
        _default_secret_warned = True
    return _DEV_SECRET


# Per-process random fallback (never committed to source)
_DEV_SECRET = hashlib.sha256(secrets.token_bytes(32)).digest()


def _make_payload(session_id: str, expiry_ts: int) -> str:
    return base64.urlsafe_b64encode(f"{session_id}|{expiry_ts}".encode()).decode()


def _parse_payload(payload: str) -> Optional[tuple[str, int]]:
    try:
        raw = base64.urlsafe_b64decode(payload.encode())
        parts = raw.decode().split("|", 1)
        if len(parts) != 2:
            return None
        return parts[0], int(parts[1])
    except Exception:
        return None


def _sign(payload: str) -> str:
    return hmac.new(_get_secret(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_cookie_value() -> tuple[str, str]:
    """Create a new session id and signed cookie value.
    Returns (consumer_identity, cookie_value).
    """
    session_id = secrets.token_urlsafe(SESSION_ID_BYTES)
    expiry = int(time.time()) + (SESSION_EXPIRY_DAYS * 86400)
    payload = _make_payload(session_id, expiry)
    sig = _sign(payload)
    cookie_value = f"{payload}.{sig}"
    identity = f"guest_{session_id}"
    return identity, cookie_value


def verify_session_cookie(cookie_value: str) -> Optional[str]:
    """Verify signed cookie and return consumer_identity (e.g. guest_xxx) or None."""
    if not cookie_value or "." not in cookie_value:
        return None
    payload, sig = cookie_value.rsplit(".", 1)
    if hmac.compare_digest(_sign(payload), sig) is False:
        return None
    parsed = _parse_payload(payload)
    if not parsed:
        return None
    session_id, expiry = parsed
    if time.time() > expiry:
        return None
    return f"guest_{session_id}"


def get_or_create_consumer_identity(cookie_value: Optional[str]) -> tuple[str, Optional[str]]:
    """Get identity from cookie or create new. Returns (consumer_identity, set_cookie_value or None).
    If set_cookie_value is not None, caller should set the response cookie.
    """
    if cookie_value:
        identity = verify_session_cookie(cookie_value)
        if identity:
            return identity, None
    identity, new_cookie = create_session_cookie_value()
    return identity, new_cookie
