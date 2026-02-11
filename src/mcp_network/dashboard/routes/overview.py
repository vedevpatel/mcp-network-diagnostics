"""Overview dashboard route."""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from mcp_network.dashboard.consumer_limits import check_consumer_rate_limit
from mcp_network.tools import check_my_connection

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _get_connection_status() -> dict:
    """Run a consumer-mode health check and return parsed JSON."""
    # Reuse the existing MCP tool implementation so logic stays in one place.
    raw = await check_my_connection()
    return json.loads(raw)


@router.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    """Render overview as a live 'My Connection' dashboard."""
    identity = getattr(request.state, "consumer_identity", None)
    if identity:
        allowed, _ = check_consumer_rate_limit(identity)
        if not allowed:
            return Response(
                content="Rate limit exceeded. Please try again in a minute.",
                status_code=429,
                media_type="text/plain",
            )
    connection = await _get_connection_status()

    return templates.TemplateResponse(
        "overview.html",
        {
            "request": request,
            "connection": connection,
        },
    )


@router.get("/partials/connection", response_class=HTMLResponse)
async def connection_partial(request: Request):
    """Return the current connection status for HTMX live updates."""
    identity = getattr(request.state, "consumer_identity", None)
    if identity:
        allowed, _ = check_consumer_rate_limit(identity)
        if not allowed:
            return Response(
                content="<div class=\"stat-value\">Rate limited</div>",
                status_code=429,
                media_type="text/html",
            )
    connection = await _get_connection_status()

    return templates.TemplateResponse(
        "partials/connection.html",
        {
            "request": request,
            "connection": connection,
            "now": datetime.now(timezone.utc),
        },
    )
