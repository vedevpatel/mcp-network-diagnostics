"""
MCP Network Diagnostics Server
"""

import logging
import sys
from mcp.server.fastmcp import FastMCP


# log to stderr for transport
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)


logger = logging.getLogger(__name__)


# iniialize fastmcp server
mcp = FastMCP("network-diagnostics")


@mcp.tool()
async def ping() -> str:
    """
    Simple ping tool to verify connectivity.
    """

    logger.info("Ping tool called")
    return "pong"


def main():
    """
    Main entry point for the MCP server.
    """

    logger.info("Starting MCP Network Diagnostics Server")
    mcp.run(transport="stdio")\
    

if __name__ == "__main__":
    main()