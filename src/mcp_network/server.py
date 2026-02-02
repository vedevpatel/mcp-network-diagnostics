"""
MCP Network Diagnostics Server
"""

import logging
import sys
from mcp_network.app import mcp
import mcp_network.tools  # noqa: F401 - registers tools with mcp


# log to stderr for transport
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)


logger = logging.getLogger(__name__)


def main():
    """
    Main entry point for the MCP server.
    """

    logger.info("Starting MCP Network Diagnostics Server")
    mcp.run(transport="stdio")\
    

if __name__ == "__main__":
    main()