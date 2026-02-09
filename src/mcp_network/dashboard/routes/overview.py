"""Overview dashboard route."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime, timezone

from mcp_network.storage import get_database, DeviceRepository, IncidentRepository, IntentRepository
from mcp_network.collectors import get_network

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def overview(request: Request):
    """Render main overview dashboard."""
    db = get_database()
    device_repo = DeviceRepository(db)
    incident_repo = IncidentRepository(db)
    intent_repo = IntentRepository(db)

    # Get current network state
    network = get_network()
    device_count = len(network.devices)

    # Get all devices from DB
    devices = device_repo.find_all()
    healthy_devices = len([d for d in devices if d.last_seen and
                          (datetime.now(timezone.utc) - d.last_seen).total_seconds() < 300])

    # Get active incidents
    active_incidents = incident_repo.find_active()
    critical_count = len([i for i in active_incidents if i.severity == "critical"])

    # Get active intents
    active_intents = intent_repo.find_active()

    # Calculate health score
    if device_count > 0:
        health_score = int((healthy_devices / device_count) * 100)
    else:
        health_score = 100

    # Get recent incidents for display
    recent_incidents = incident_repo.find_recent(days=1, limit=5)

    return templates.TemplateResponse("overview.html", {
        "request": request,
        "health_score": health_score,
        "device_count": device_count,
        "healthy_devices": healthy_devices,
        "active_incident_count": len(active_incidents),
        "critical_incident_count": critical_count,
        "active_intent_count": len(active_intents),
        "recent_incidents": recent_incidents,
        "now": datetime.now(timezone.utc),
    })


@router.get("/partials/incidents", response_class=HTMLResponse)
async def incidents_partial(request: Request):
    """Get incidents partial for HTMX updates."""
    db = get_database()
    incident_repo = IncidentRepository(db)

    recent_incidents = incident_repo.find_recent(days=1, limit=5)

    return templates.TemplateResponse("partials/incidents.html", {
        "request": request,
        "recent_incidents": recent_incidents,
        "now": datetime.now(timezone.utc),
    })
