"""Settings dashboard routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from mcp_network.security import AuthManager
from mcp_network.notifications import NotificationRouter

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def settings_page(request: Request):
    """Show settings page."""
    # Get API keys
    auth_mgr = AuthManager()
    api_keys = auth_mgr.list_keys()

    # Get notification channels
    # Note: In production, would persist router state
    router_instance = NotificationRouter()

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "api_keys": api_keys,
        "notification_channels": list(router_instance.channels.keys()),
    })
