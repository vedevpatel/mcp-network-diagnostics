"""FastAPI application for web dashboard."""

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .routes import overview, devices, incidents, intents, settings, tools, status, developer
from mcp_network.storage.tenant import set_tenant_id

from .session import (
    SESSION_COOKIE_NAME,
    SESSION_EXPIRY_DAYS,
    get_or_create_consumer_identity,
)


class ConsumerSessionMiddleware(BaseHTTPMiddleware):
    """Ensures consumer_identity on request.state (guest session from signed cookie)."""

    async def dispatch(self, request, call_next):
        cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
        identity, new_cookie = get_or_create_consumer_identity(cookie_value)
        request.state.consumer_identity = identity
        set_tenant_id(identity)
        if new_cookie:
            request.state._set_session_cookie = new_cookie
        response = await call_next(request)
        if getattr(request.state, "_set_session_cookie", None):
            response.set_cookie(
                SESSION_COOKIE_NAME,
                request.state._set_session_cookie,
                max_age=SESSION_EXPIRY_DAYS * 86400,
                httponly=True,
                samesite="lax",
                path="/",
            )
        return response


def create_app() -> FastAPI:
    """Create and configure FastAPI application.

    Returns:
        Configured FastAPI app
    """
    app = FastAPI(
        title="MCP Network Diagnostics Dashboard",
        description="Real-time network monitoring and diagnostics",
        version="1.0.0",
    )

    # Consumer session (guest identity) – runs first so routes see request.state.consumer_identity
    app.add_middleware(ConsumerSessionMiddleware)

    # Mount static files
    static_path = Path(__file__).parent / "static"
    static_path.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    # Include routers
    app.include_router(overview.router, tags=["Overview"])
    app.include_router(devices.router, prefix="/devices", tags=["Devices"])
    app.include_router(incidents.router, prefix="/incidents", tags=["Incidents"])
    app.include_router(intents.router, prefix="/intents", tags=["Intents"])
    app.include_router(settings.router, prefix="/settings", tags=["Settings"])
    app.include_router(tools.router, prefix="/tools", tags=["Tools"])
    app.include_router(status.router, tags=["Status"])
    app.include_router(developer.router, prefix="/developer", tags=["Developer"])

    return app


# For running with uvicorn
app = create_app()
