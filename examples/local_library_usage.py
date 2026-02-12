"""
Example: Using mcp-network as a library.

This script demonstrates how to import and run diagnostic tools directly
without an MCP client.
"""

import asyncio
import os
import json

# Set "full" mode to allow local execution without restrictions
os.environ["MCP_NETWORK_STDIO_MODE"] = "full"

from mcp_network import check_my_connection, why_is_it_slow

async def main():
    print("=== Running Network Diagnostics Library Example ===\n")

    # 1. Check local connection health
    print("1. Checking connection health...")
    result_json = await check_my_connection()
    result = json.loads(result_json)
    
    print(f"   Status: {result.get('overall_status', 'unknown')}")
    print(f"   Gateway Latency: {result['layers']['local_network']['latency_ms']}ms")
    print(f"   Internet Latency: {result['layers']['internet']['latency_to_8888_ms']}ms")
    print("-" * 40)

    # 2. Diagnose a specific target
    target = "8.8.8.8"
    print(f"\n2. Diagnosing path to {target}...")
    diagnosis = await why_is_it_slow(target)
    print(f"   Diagnosis: {diagnosis[:100]}...") # Print snippet
    
    print("\n=== Done ===")

if __name__ == "__main__":
    asyncio.run(main())
