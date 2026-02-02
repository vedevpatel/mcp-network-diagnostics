"""
MCP Network Diagnostics Server
"""

import argparse
import os
import logging
import sys
from mcp_network.app import mcp


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

    parser = argparse.ArgumentParser(description="MCP Network Diagnostics Server")

    parser.add_argument(
        "--collector",
        type=str,
        choices=["simulated", "prometheus"],
        default=os.getenv("MCP_NETWORK_COLLECTOR", "simulated"),
        help="Network data collector type (default: simulated)"
    )

    parser.add_argument(
        "--prometheus-url",
        type=str,
        default=os.getenv("MCP_NETWORK_PROMETHEUS_URL", "http://localhost:9090"),
        help="Prometheus server URL (default: http://localhost:9090)"
    )

    parser.add_argument(
        "--topology-file",
        type=str,
        default=os.getenv("MCP_NETWORK_TOPOLOGY_FILE", "network_topology.yaml"),
        help="Path to network topology configuration file"
    )

    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=int(os.getenv("MCP_NETWORK_CACHE_TTL", "30")),
        help="Metric cache TTL in seconds (default: 30)"
    )

    args = parser.parse_args()

    # Initialize collector based on type
    from mcp_network.collectors import configure_collector
    configure_collector(
        collector_type=args.collector,
        prometheus_url=args.prometheus_url,
        topology_file=args.topology_file,
        cache_ttl=args.cache_ttl
    )

    import mcp_network.tools  # noqa: F401

    logger.info(f"Starting MCP Network Diagnostics Server with {args.collector} collector")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()