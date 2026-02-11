"""Tools dashboard: run MCP tools from the UI and show output."""

import html
from pathlib import Path

from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from mcp_network.dashboard.auth_deps import require_dashboard_auth
from mcp_network.dashboard.consumer_limits import check_consumer_rate_limit
from mcp_network.security.validation import InputValidator, ValidationError

_validator = InputValidator()

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

# Tool definitions: id = function name in mcp_network.tools, label, category, description, params
TOOL_DEFINITIONS = [
    # Consumer
    {"id": "check_my_connection", "label": "Check my connection", "category": "consumer", "description": "Quick health check: WiFi, gateway, DNS, internet.", "params": []},
    {"id": "trace_path", "label": "Trace path", "category": "consumer", "description": "Traceroute to a host with AS/latency per hop.", "params": [{"name": "destination", "type": "text", "label": "Destination", "placeholder": "e.g. cisco.com or 8.8.8.8", "default": ""}]},
    {"id": "why_is_it_slow", "label": "Why is it slow?", "category": "consumer", "description": "Diagnose latency to a destination.", "params": [{"name": "destination", "type": "text", "label": "Destination", "placeholder": "e.g. zoom.us", "default": ""}]},
    {"id": "record_baseline", "label": "Record baseline", "category": "consumer", "description": "Record current state as baseline for anomaly detection.", "params": []},
    {"id": "compare_to_baseline", "label": "Compare to baseline", "category": "consumer", "description": "Compare current connection to stored baseline.", "params": []},
    {"id": "clear_baseline", "label": "Clear baseline", "category": "consumer", "description": "Reset baseline data.", "params": []},
    {"id": "run_speedtest", "label": "Run speedtest", "category": "consumer", "description": "Bandwidth test (requires speedtest-cli).", "params": []},
    # Operator
    {"id": "list_devices", "label": "List devices", "category": "operator", "description": "List all devices in the topology.", "params": []},
    {"id": "get_device_status", "label": "Device status", "category": "operator", "description": "CPU, memory, interfaces for a device.", "params": [{"name": "device_id", "type": "text", "label": "Device ID", "placeholder": "e.g. R1", "default": ""}]},
    {"id": "get_path", "label": "Get path", "category": "operator", "description": "Shortest path between two devices.", "params": [{"name": "src_device", "type": "text", "label": "Source", "placeholder": "R1", "default": ""}, {"name": "dst_device", "type": "text", "label": "Destination", "placeholder": "R5", "default": ""}]},
    {"id": "diagnose_latency", "label": "Diagnose latency", "category": "operator", "description": "Analyze latency along path between two devices.", "params": [{"name": "src_device", "type": "text", "label": "Source", "placeholder": "R1", "default": ""}, {"name": "dst_device", "type": "text", "label": "Destination", "placeholder": "R5", "default": ""}]},
    {"id": "refresh_metrics", "label": "Refresh metrics", "category": "operator", "description": "Update metrics (simulated collector).", "params": []},
    {"id": "detect_anomalies", "label": "Detect anomalies", "category": "operator", "description": "Statistical anomaly detection on collected metrics.", "params": []},
    {"id": "get_collection_health", "label": "Collection health", "category": "operator", "description": "Health of data collection (SSH/Prometheus).", "params": []},
    {"id": "run_command", "label": "Run command", "category": "operator", "description": "Run a read-only command on a device.", "params": [{"name": "device_id", "type": "text", "label": "Device ID", "placeholder": "R1", "default": ""}, {"name": "command", "type": "text", "label": "Command", "placeholder": "show ip interface brief", "default": ""}]},
    {"id": "get_config_history", "label": "Config history", "category": "operator", "description": "Recent config snapshots for a device.", "params": [{"name": "device_id", "type": "text", "label": "Device ID", "placeholder": "R1", "default": ""}, {"name": "limit", "type": "number", "label": "Limit", "placeholder": "10", "default": "10"}]},
    # Agent
    {"id": "start_agent", "label": "Start agent", "category": "agent", "description": "Start the continuous monitoring agent.", "params": [{"name": "poll_interval_seconds", "type": "number", "label": "Poll interval (s)", "placeholder": "60", "default": "60"}]},
    {"id": "stop_agent", "label": "Stop agent", "category": "agent", "description": "Stop the monitoring agent.", "params": []},
    {"id": "set_intent", "label": "Set intent", "category": "agent", "description": "Add a monitoring goal in natural language.", "params": [{"name": "goal", "type": "text", "label": "Goal", "placeholder": "Zoom should stay under 100ms", "default": ""}, {"name": "priority", "type": "number", "label": "Priority (1-10)", "placeholder": "5", "default": "5"}]},
    {"id": "list_intents", "label": "List intents", "category": "agent", "description": "Show all monitoring intents.", "params": []},
    {"id": "remove_intent", "label": "Remove intent", "category": "agent", "description": "Remove an intent by ID.", "params": [{"name": "intent_id", "type": "text", "label": "Intent ID", "placeholder": "uuid or id", "default": ""}]},
    {"id": "get_incidents", "label": "Get incidents", "category": "agent", "description": "Recent incidents from the agent.", "params": [{"name": "limit", "type": "number", "label": "Limit", "placeholder": "10", "default": "10"}]},
    {"id": "agent_status", "label": "Agent status", "category": "agent", "description": "Whether the agent is running and summary.", "params": []},
    {"id": "plan_goal", "label": "Plan goal", "category": "agent", "description": "Generate an action plan from a natural language goal.", "params": [{"name": "goal", "type": "text", "label": "Goal", "placeholder": "Keep Zoom responsive during work hours", "default": ""}]},
    {"id": "execute_plan", "label": "Execute plan", "category": "agent", "description": "Activate a plan by intent ID.", "params": [{"name": "intent_id", "type": "text", "label": "Intent ID", "placeholder": "from plan_goal", "default": ""}]},
    {"id": "get_guardrail_status", "label": "Guardrail status", "category": "agent", "description": "Alert cooldowns and rate limits.", "params": []},
]


def _get_tool_fn(tool_id: str):
    """Return the async tool function by id."""
    import mcp_network.tools as mod
    if not hasattr(mod, tool_id):
        return None
    return getattr(mod, tool_id)


def _build_kwargs(tool_def: dict, form_data: dict) -> dict:
    """Build kwargs from form data using tool param definitions."""
    kwargs = {}
    for p in tool_def.get("params", []):
        name = p["name"]
        raw = form_data.get(name)
        if raw is None or (isinstance(raw, str) and raw.strip() == ""):
            default = p.get("default")
            if default != "" and default is not None:
                raw = default
            else:
                continue
        if isinstance(raw, str):
            raw = raw.strip()
        if p.get("type") == "number":
            try:
                if "." in str(raw):
                    kwargs[name] = float(raw)
                else:
                    kwargs[name] = int(raw)
            except (ValueError, TypeError):
                kwargs[name] = raw
        else:
            kwargs[name] = raw
    return kwargs


def _render_output_fragment(output: str, error: bool = False) -> str:
    """Return HTML fragment for tool output (for HTMX swap)."""
    escaped = html.escape(output) if output else "(no output)"
    css = "tool-output tool-output-error" if error else "tool-output"
    return f'<pre class="{css}" id="tool-output-pre">{escaped}</pre>'


def _render_error_fragment(message: str) -> str:
    return _render_output_fragment(message, error=True)


@router.get("/", response_class=HTMLResponse)
async def tools_page(request: Request, _auth=Depends(require_dashboard_auth)):
    """Render the tools page with all tool buttons/forms."""
    by_category = {}
    for t in TOOL_DEFINITIONS:
        cat = t["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(t)
    categories_order = ["consumer", "operator", "agent"]
    categories = [{"id": c, "label": {"consumer": "My connection", "operator": "Network", "agent": "Monitoring"}[c], "tools": by_category.get(c, [])} for c in categories_order]

    return templates.TemplateResponse("tools.html", {
        "request": request,
        "categories": categories,
    })


@router.post("/invoke", response_class=HTMLResponse)
async def invoke_tool(request: Request, _auth=Depends(require_dashboard_auth)):
    """Invoke a tool by id with form params; return HTML fragment for output."""
    identity = getattr(request.state, "consumer_identity", None)
    if identity:
        allowed, retry_after = check_consumer_rate_limit(identity)
        if not allowed:
            return Response(
                content=_render_error_fragment(
                    f"Rate limit exceeded. Try again in {int(retry_after)} seconds."
                ),
                status_code=429,
                media_type="text/html",
            )
    form_dict = dict(await request.form())
    tool_id = form_dict.pop("tool_id", None)
    if not tool_id:
        return _render_error_fragment("Missing tool_id")

    tool_def = next((t for t in TOOL_DEFINITIONS if t["id"] == tool_id), None)
    if not tool_def:
        return _render_error_fragment(f"Unknown tool: {tool_id}")

    fn = _get_tool_fn(tool_id)
    if not fn or not callable(fn):
        return _render_error_fragment(f"Tool not found: {tool_id}")

    kwargs = _build_kwargs(tool_def, form_dict)

    # Validate consumer-facing inputs (destination, goal, etc.)
    try:
        if "destination" in kwargs:
            kwargs["destination"] = _validator.validate_destination(kwargs["destination"])
        if "goal" in kwargs:
            kwargs["goal"] = _validator.validate_intent(kwargs["goal"])
        if "device_id" in kwargs:
            kwargs["device_id"] = _validator.validate_device_id(kwargs["device_id"])
        if "command" in kwargs:
            kwargs["command"] = _validator.validate_command(kwargs["command"])
    except ValidationError as e:
        return _render_error_fragment(str(e))

    try:
        result = await fn(**kwargs)
        return _render_output_fragment(result)
    except Exception as e:
        return _render_error_fragment(str(e))
