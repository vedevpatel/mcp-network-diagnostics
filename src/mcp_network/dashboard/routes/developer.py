"""Developer / API docs for the MCP server."""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mcp_network.security.permissions import TOOL_PERMISSIONS
from mcp_network.security import Role

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# Build flat list of tools per role for the template
ROLE_TOOLS = {
    "consumer": sorted(TOOL_PERMISSIONS.get(Role.CONSUMER, [])),
    "operator": sorted(TOOL_PERMISSIONS.get(Role.OPERATOR, [])),
    "admin": sorted(TOOL_PERMISSIONS.get(Role.ADMIN, [])),
    "superuser": sorted(TOOL_PERMISSIONS.get(Role.SUPERUSER, [])),
}


@router.get("/", response_class=HTMLResponse)
async def developer_page(request: Request):
    """Developer docs: auth, roles, tools."""
    return templates.TemplateResponse("developer.html", {
        "request": request,
        "role_tools": ROLE_TOOLS,
    })
