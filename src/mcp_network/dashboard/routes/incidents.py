"""Incidents dashboard routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from mcp_network.storage import get_database, IncidentRepository

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def incidents_list(request: Request, days: int = 7):
    """List incidents."""
    db = get_database()
    incident_repo = IncidentRepository(db)

    incidents = incident_repo.find_recent(days=days, limit=100)

    return templates.TemplateResponse("incidents.html", {
        "request": request,
        "incidents": incidents,
        "days": days,
    })


@router.get("/{incident_id}", response_class=HTMLResponse)
async def incident_detail(request: Request, incident_id: str):
    """Show incident details."""
    db = get_database()
    incident_repo = IncidentRepository(db)

    incident = incident_repo.find_by_id(incident_id)
    if not incident:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Incident {incident_id} not found",
        })

    return templates.TemplateResponse("incident_detail.html", {
        "request": request,
        "incident": incident,
    })
