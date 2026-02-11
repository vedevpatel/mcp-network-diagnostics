"""Shared test configuration."""

import os

# Allow all tools in tests (stdio mode defaults to consumer-only).
os.environ.setdefault("MCP_NETWORK_STDIO_MODE", "full")
