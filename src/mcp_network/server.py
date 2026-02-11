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


# Configure collector from environment variables at module load time
# This ensures tools are registered when mcp dev imports the module
from mcp_network.collectors import configure_collector
configure_collector(
    collector_type=os.getenv("MCP_NETWORK_COLLECTOR", "simulated"),
    prometheus_url=os.getenv("MCP_NETWORK_PROMETHEUS_URL", "http://localhost:9090"),
    topology_file=os.getenv("MCP_NETWORK_TOPOLOGY_FILE", "network_topology.yaml"),
    cache_ttl=int(os.getenv("MCP_NETWORK_CACHE_TTL", "30"))
)

# Import tools to register them with the mcp server
import mcp_network.tools  # noqa: F401


def main():
    """
    Main entry point for the MCP server.
    """
    parser = argparse.ArgumentParser(description="MCP Network Diagnostics Server")

    parser.add_argument(
        "--collector",
        type=str,
        choices=["simulated", "prometheus", "iosxr", "iosxe", "ssh"],
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

    parser.add_argument(
        "--transport",
        type=str,
        choices=["stdio", "streamable-http"],
        default=os.getenv("MCP_NETWORK_TRANSPORT", "stdio"),
        help="Transport: stdio (default, for Claude Desktop) or streamable-http (for remote API)"
    )

    parser.add_argument(
        "--host",
        type=str,
        default=os.getenv("MCP_NETWORK_HTTP_HOST", "0.0.0.0"),
        help="Bind host for streamable-http (default: 0.0.0.0)"
    )

    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("MCP_NETWORK_HTTP_PORT", "8000")),
        help="Port for streamable-http (default: 8000)"
    )

    parser.add_argument(
        "--path",
        type=str,
        default=os.getenv("MCP_NETWORK_HTTP_PATH", "/mcp"),
        help="URL path for streamable-http (default: /mcp)"
    )

    parser.add_argument(
        "--require-auth",
        action="store_true",
        default=os.getenv("MCP_NETWORK_REQUIRE_AUTH", "").lower() in ("1", "true", "yes"),
        help="Require API key for HTTP transport (env: MCP_NETWORK_REQUIRE_AUTH)"
    )

    parser.add_argument(
        "--api-keys-file",
        type=str,
        default=os.getenv("MCP_NETWORK_API_KEYS_FILE", ""),
        help="Path to API keys JSON (default: ~/.mcp_network/api_keys.json)"
    )

    args = parser.parse_args()

    # Re-configure collector with CLI args (overrides env vars)
    configure_collector(
        collector_type=args.collector,
        prometheus_url=args.prometheus_url,
        topology_file=args.topology_file,
        cache_ttl=args.cache_ttl
    )

    if args.transport == "stdio":
        logger.info(f"Starting MCP Network Diagnostics Server with {args.collector} collector (stdio)")
        mcp.run(transport="stdio")
    else:
        # Security: warn loudly when binding to all interfaces without auth
        if args.host in ("0.0.0.0", "::") and not args.require_auth:
            logger.warning(
                "SECURITY WARNING: HTTP server binds to all interfaces (%s) "
                "without authentication. Anyone with network access can call "
                "any MCP tool. Use --require-auth or bind to 127.0.0.1.",
                args.host,
            )

        # streamable-http: run with optional auth and rate limiting
        from mcp_network.server_http import run_http
        run_http(
            host=args.host,
            port=args.port,
            path=args.path,
            require_auth=args.require_auth,
            api_keys_file=args.api_keys_file or None,
        )


if __name__ == "__main__":
    main()