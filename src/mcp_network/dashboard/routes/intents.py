"""Intents dashboard routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pathlib import Path

from mcp_network.storage import get_database, IntentRepository

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/", response_class=HTMLResponse)
async def intents_list(request: Request):
    """List all intents."""
    db = get_database()
    intent_repo = IntentRepository(db)

    intents = intent_repo.find_all()

    return templates.TemplateResponse("intents.html", {
        "request": request,
        "intents": intents,
    })
