"""
MCP Server instance - shared across modules to avoid circular imports.
"""

from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server instance
mcp = FastMCP("network-diagnostics")
