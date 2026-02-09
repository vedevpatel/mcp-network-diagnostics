"""Devices dashboard routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path
from datetime import datetime, timezone, timedelta

from mcp_network.storage import get_database, DeviceRepository, MetricRepository, IncidentRepository

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def devices_list(request: Request):
    """List all devices."""
    db = get_database()
    device_repo = DeviceRepository(db)

    devices = device_repo.find_all()

    # Enrich with health status
    now = datetime.now(timezone.utc)
    device_list = []
    for device in devices:
        age_seconds = (now - device.last_seen).total_seconds() if device.last_seen else 999999
        status = "healthy" if age_seconds < 300 else "stale"

        device_list.append({
            "id": device.id,
            "name": device.name,
            "type": device.device_type,
            "status": status,
            "last_seen": device.last_seen,
        })

    return templates.TemplateResponse("devices.html", {
        "request": request,
        "devices": device_list,
    })


@router.get("/{device_id}", response_class=HTMLResponse)
async def device_detail(request: Request, device_id: str):
    """Show device details."""
    db = get_database()
    device_repo = DeviceRepository(db)
    metric_repo = MetricRepository(db)
    incident_repo = IncidentRepository(db)

    device = device_repo.find_by_id(device_id)
    if not device:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": f"Device {device_id} not found",
        })

    # Get recent metrics
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=24)

    cpu_metrics = metric_repo.query(device_id, "cpu", start_time, end_time, limit=100)

    # Get recent incidents
    incidents = incident_repo.find_by_device(device_id, days=7)

    return templates.TemplateResponse("device_detail.html", {
        "request": request,
        "device": device,
        "cpu_metrics": cpu_metrics[-20:] if cpu_metrics else [],  # Last 20 points
        "incidents": incidents[:10],  # Last 10 incidents
    })
