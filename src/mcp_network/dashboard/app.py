"""FastAPI application for web dashboard."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from .routes import overview, devices, incidents, intents, settings, tools, status, developer


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
