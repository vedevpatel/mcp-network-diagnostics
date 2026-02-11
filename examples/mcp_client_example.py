#!/usr/bin/env python3
"""
Example: Connect to MCP Network Diagnostics server and call consumer tools.

This demonstrates programmatic MCP client usage. For Claude Desktop integration,
see the README.md or docs/MCP_QUICKSTART.md.

Requirements:
    pip install mcp

Usage:
    # Start the server first (in another terminal):
    uv run mcp-network

    # Then run this script:
    python examples/mcp_client_example.py
"""

import asyncio
import json
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    # Connect to the MCP server via stdio
    server_params = StdioServerParameters(
        command="uv",
        args=["--directory", ".", "run", "mcp-network"],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the session
            await session.initialize()

            # List available tools
            tools = await session.list_tools()
            print("Available tools:")
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description[:60]}...")
            print()

            # Call check_my_connection
            print("Calling check_my_connection()...")
            result = await session.call_tool("check_my_connection", {})
            data = json.loads(result.content[0].text)
            print(f"Overall status: {data.get('overall_status', 'unknown')}")
            if "layers" in data:
                layers = data["layers"]
                if "wifi" in layers and layers["wifi"].get("ssid"):
                    print(f"WiFi: {layers['wifi']['ssid']} ({layers['wifi'].get('quality', 'unknown')})")
                if "local_network" in layers:
                    ln = layers["local_network"]
                    print(f"Gateway: {ln.get('gateway_ip')} ({ln.get('latency_ms', '?')}ms)")
            print()

            # Call why_is_it_slow for a target
            print("Calling why_is_it_slow('google.com')...")
            result = await session.call_tool("why_is_it_slow", {"destination": "google.com"})
            data = json.loads(result.content[0].text)
            if "diagnosis" in data:
                diag = data["diagnosis"]
                print(f"Bottleneck: {diag.get('bottleneck', 'unknown')}")
                print(f"Confidence: {diag.get('confidence', 0):.0%}")
                print(f"Summary: {diag.get('summary', 'N/A')}")
            if data.get("suggestions"):
                print("Suggestions:")
                for s in data["suggestions"][:3]:
                    print(f"  - {s}")


if __name__ == "__main__":
    asyncio.run(main())
