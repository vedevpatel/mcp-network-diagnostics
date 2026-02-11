"""System status for the dashboard: agent and collection health."""

import json
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


async def _get_agent_status_data() -> dict | None:
    """Call agent_status tool and return parsed JSON.
    
    Returns None if the tool is not available (e.g., consumer mode).
    """
    try:
        from mcp_network.tools import agent_status
        raw = await agent_status()
        return json.loads(raw)
    except PermissionError:
        # Tool not available in consumer mode
        return None
    except Exception:
        return None


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
    if agent_data is None:
        # Agent status not available (consumer mode or permission denied)
        agent_label = "Consumer mode"
        agent_class = "status-not-started"
    else:
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

    # Collection: show only when we have data (operator mode)
    collection_html = ""
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
            collection_html = f'<span class="system-status-item"><span class="system-status-label">Collection</span> <span class="system-status-dot {coll_class}" aria-hidden="true"></span> <span class="system-status-value">{coll_label}</span></span>'

    return templates.TemplateResponse("partials/status_bar.html", {
        "request": request,
        "agent_label": agent_label,
        "agent_class": agent_class,
        "collection_html": collection_html,
    })


@router.get("/status/dev", response_class=JSONResponse)
async def dev_status(request: Request):
    """Return developer-focused status info: transports, config, features.
    
    Helps developers debug deployments and verify configuration.
    """
    # Detect collector mode
    collector_mode = "consumer"  # Dashboard runs in consumer mode by default
    try:
        from mcp_network.tools import list_devices
        # If list_devices is available and returns devices, we're in operator mode
        result = await list_devices()
        data = json.loads(result)
        if data.get("devices"):
            collector_mode = "operator"
    except Exception:
        pass
    
    # Check agent availability
    agent_available = False
    try:
        from mcp_network.tools import agent_status
        result = await agent_status()
        data = json.loads(result)
        agent_available = data.get("status") != "not_initialized" or True  # Available if we can call it
    except PermissionError:
        agent_available = False
    except Exception:
        agent_available = True  # Tool exists, just errored
    
    # Environment-based config
    config = {
        "transport": "dashboard",  # Dashboard uses its own FastAPI server
        "mcp_transports_available": ["stdio", "streamable-http"],
        "collector_mode": collector_mode,
        "features": {
            "agent": agent_available,
            "baselines": True,
            "rate_limiting": True,
            "guest_sessions": True,
        },
        "rate_limits": {
            "consumer_per_minute": int(os.getenv("CONSUMER_RATE_LIMIT_PER_MINUTE", "60")),
            "global_per_minute": int(os.getenv("MCP_NETWORK_GLOBAL_RPM", "1000")),
        },
        "auth": {
            "dashboard_auth_required": os.getenv("MCP_NETWORK_DASHBOARD_REQUIRE_AUTH", "0") == "1",
            "cors_origins": os.getenv("MCP_NETWORK_CORS_ORIGINS", ""),
        },
        "docs": {
            "readme": "https://github.com/vedevpatel/mcp-network-diagnostics#readme",
            "mcp_quickstart": "https://github.com/vedevpatel/mcp-network-diagnostics/blob/main/docs/MCP_QUICKSTART.md",
            "security": "https://github.com/vedevpatel/mcp-network-diagnostics/blob/main/SECURITY.md",
        },
    }
    
    return JSONResponse(config)
