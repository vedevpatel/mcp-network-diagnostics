"""Dashboard auth: require API key for protected routes when MCP_NETWORK_DASHBOARD_REQUIRE_AUTH is set."""

import os
from pathlib import Path
from typing import Optional

from fastapi import Header, Query, HTTPException

from mcp_network.security import Role
from mcp_network.storage.tenant import set_tenant_id


def _get_auth_manager():
    from mcp_network.security import AuthManager
    keys_file = os.getenv("MCP_NETWORK_API_KEYS_FILE") or str(Path.home() / ".mcp_network" / "api_keys.json")
    return AuthManager(keys_file)


def _extract_bearer(value: Optional[str]) -> Optional[str]:
    if not value or not value.strip().lower().startswith("bearer "):
        return None
    return value.strip()[7:].strip()


def _dashboard_auth_required() -> bool:
    return os.getenv("MCP_NETWORK_DASHBOARD_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")


def require_dashboard_auth(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    api_key: Optional[str] = Query(None, alias="api_key"),
):
    """Dependency: when MCP_NETWORK_DASHBOARD_REQUIRE_AUTH is set, require valid API key.
    Key can be in Authorization: Bearer <key>, X-API-Key header, or ?api_key= query (GET only).
    Returns validated APIKey or None (when auth not required).
    """
    if not _dashboard_auth_required():
        return None

    key_str = _extract_bearer(authorization) or x_api_key or api_key
    if not key_str:
        raise HTTPException(
            status_code=401,
            detail="API key required. Set MCP_NETWORK_DASHBOARD_REQUIRE_AUTH=0 to disable, or provide Authorization: Bearer mcp_xxx, X-API-Key, or ?api_key=.",
            headers={"WWW-Authenticate": 'Bearer realm="Dashboard"'},
        )

    auth_mgr = _get_auth_manager()
    api_key_obj = auth_mgr.authenticate(key_str)
    if not api_key_obj:
        raise HTTPException(status_code=401, detail="Invalid or expired API key.")
    # Operator/admin: scope storage and tools to this key's tenant
    if api_key_obj.role in (Role.OPERATOR, Role.ADMIN, Role.SUPERUSER):
        set_tenant_id(api_key_obj.tenant_id or api_key_obj.key_id)
    return api_key_obj
