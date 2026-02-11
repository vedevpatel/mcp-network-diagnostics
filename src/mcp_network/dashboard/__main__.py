"""Dashboard entry point."""

import logging
import os

import uvicorn
from .app import create_app

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    app = create_app()

    host = os.getenv("MCP_NETWORK_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_NETWORK_DASHBOARD_PORT", "8080"))

    # Security: warn when binding to all interfaces without auth
    if host in ("0.0.0.0", "::"):
        auth_required = os.getenv("MCP_NETWORK_DASHBOARD_REQUIRE_AUTH", "").lower() in (
            "1", "true", "yes",
        )
        if not auth_required:
            logger.warning(
                "SECURITY WARNING: Dashboard binds to all interfaces (%s) "
                "without authentication. Set MCP_NETWORK_DASHBOARD_REQUIRE_AUTH=1 "
                "or bind to 127.0.0.1 (MCP_NETWORK_DASHBOARD_HOST).",
                host,
            )

    uvicorn.run(app, host=host, port=port)
