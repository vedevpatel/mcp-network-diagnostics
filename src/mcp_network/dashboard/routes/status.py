"""System status for the dashboard: agent and collection health."""

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _get_agent_status_data() -> dict:
    """Call agent_status tool and return parsed JSON."""
    from mcp_network.tools import agent_status
    raw = await agent_status()
    return json.loads(raw)


async def _get_collection_status_data() -> dict | None:
    """Call get_collection_health if available (operator mode); return None on failure."""
    try:
        from mcp_network.tools import get_collection_health
        raw = await get_collection_health()
        return json.loads(raw)
    except Exception:
        return None


@router.get("/partials/status", response_class=HTMLResponse)
async def status_partial(request: Request):
    """Return the system status bar HTML fragment (for HTMX)."""
    agent_data = await _get_agent_status_data()
    collection_data = await _get_collection_status_data()

    # Normalize agent state for display
    agent_status_str = agent_data.get("status", "unknown")
    if agent_status_str == "not_initialized":
        agent_label = "Not started"
        agent_class = "status-not-started"
    elif agent_status_str == "running":
        agent_label = "Running"
        agent_class = "status-running"
        intents = agent_data.get("intents", {})
        total = intents.get("total", 0)
        if total:
            agent_label = f"Running ({total} intent{'s' if total != 1 else ''})"
    else:
        agent_label = "Stopped"
        agent_class = "status-stopped"

    # Collection: pass structured data (not pre-rendered HTML) to avoid XSS
    collection_info = None
    if collection_data is not None:
        score = collection_data.get("collection_quality_score", 0)
        reachable = collection_data.get("reachable_devices", 0)
        total_dev = collection_data.get("total_devices", 0)
        if total_dev and total_dev > 0:
            pct = int((reachable / total_dev) * 100)
            if score >= 0.8 and pct == 100:
                coll_class = "status-running"
                coll_label = "Healthy"
            elif score >= 0.5 or pct >= 50:
                coll_class = "status-degraded"
                coll_label = f"Degraded ({pct}% reachable)"
            else:
                coll_class = "status-stopped"
                coll_label = f"Unhealthy ({pct}% reachable)"
            collection_info = {"css_class": coll_class, "label": coll_label}

    return templates.TemplateResponse("partials/status_bar.html", {
        "request": request,
        "agent_label": agent_label,
        "agent_class": agent_class,
        "collection_info": collection_info,
    })
