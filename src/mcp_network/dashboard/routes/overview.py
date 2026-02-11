"""Overview dashboard route."""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from mcp_network.dashboard.consumer_limits import check_consumer_rate_limit
from mcp_network.tools import check_my_connection

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# TTL cache for connection status to avoid re-probing on rapid page loads
_connection_cache: dict = {"data": None, "expires": 0.0}
CACHE_TTL_SECONDS = 10


async def _get_connection_status() -> dict:
    """Run a consumer-mode health check and return parsed JSON.
    
    Results are cached for CACHE_TTL_SECONDS to speed up page navigation.
    """
    now = time.time()
    if _connection_cache["data"] and now < _connection_cache["expires"]:
        return _connection_cache["data"]
    
    raw = await check_my_connection()
    data = json.loads(raw)
    _connection_cache["data"] = data
    _connection_cache["expires"] = now + CACHE_TTL_SECONDS
    return data


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
