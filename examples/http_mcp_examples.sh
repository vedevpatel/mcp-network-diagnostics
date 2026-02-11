#!/bin/bash
# HTTP MCP API Examples
#
# Start the server first:
#   uv run mcp-network --transport streamable-http --port 8000 --path /mcp
#
# For authenticated endpoints, add --require-auth and set your API key below.

BASE_URL="${BASE_URL:-http://localhost:8000}"
MCP_PATH="${MCP_PATH:-/mcp}"
API_KEY="${API_KEY:-}"  # Set this for authenticated requests

# Helper to make MCP JSON-RPC calls
mcp_call() {
    local method=$1
    local params=$2
    local id=${3:-1}
    
    local auth_header=""
    if [ -n "$API_KEY" ]; then
        auth_header="-H \"Authorization: Bearer $API_KEY\""
    fi
    
    eval curl -s -X POST "${BASE_URL}${MCP_PATH}" \
        -H "Content-Type: application/json" \
        $auth_header \
        -d "{\"jsonrpc\":\"2.0\",\"id\":$id,\"method\":\"$method\",\"params\":$params}"
}

echo "=== MCP HTTP API Examples ==="
echo "Server: ${BASE_URL}${MCP_PATH}"
echo ""

# -----------------------------------------------------------------------------
# 1. List available tools
# -----------------------------------------------------------------------------
echo "1. List available tools"
echo "   Method: tools/list"
echo ""
mcp_call "tools/list" "{}" | python3 -m json.tool 2>/dev/null || echo "(JSON parse failed)"
echo ""

# -----------------------------------------------------------------------------
# 2. Call check_my_connection
# -----------------------------------------------------------------------------
echo "2. Call check_my_connection"
echo "   Method: tools/call"
echo ""
mcp_call "tools/call" '{"name":"check_my_connection","arguments":{}}' | python3 -m json.tool 2>/dev/null || echo "(JSON parse failed)"
echo ""

# -----------------------------------------------------------------------------
# 3. Call why_is_it_slow with a target
# -----------------------------------------------------------------------------
echo "3. Call why_is_it_slow('google.com')"
echo "   Method: tools/call"
echo ""
mcp_call "tools/call" '{"name":"why_is_it_slow","arguments":{"destination":"google.com"}}' | python3 -m json.tool 2>/dev/null || echo "(JSON parse failed)"
echo ""

# -----------------------------------------------------------------------------
# 4. Call trace_path
# -----------------------------------------------------------------------------
echo "4. Call trace_path('8.8.8.8')"
echo "   Method: tools/call"
echo ""
mcp_call "tools/call" '{"name":"trace_path","arguments":{"destination":"8.8.8.8"}}' | python3 -m json.tool 2>/dev/null || echo "(JSON parse failed)"
echo ""

# -----------------------------------------------------------------------------
# 5. Call scan_local_network
# -----------------------------------------------------------------------------
echo "5. Call scan_local_network"
echo "   Method: tools/call"
echo ""
mcp_call "tools/call" '{"name":"scan_local_network","arguments":{}}' | python3 -m json.tool 2>/dev/null || echo "(JSON parse failed)"
echo ""

# -----------------------------------------------------------------------------
# Usage notes
# -----------------------------------------------------------------------------
echo "=== Usage Notes ==="
echo ""
echo "To use with authentication:"
echo "  export API_KEY=mcp_your_key_here"
echo "  ./http_mcp_examples.sh"
echo ""
echo "To use a different server:"
echo "  BASE_URL=http://your-server:8000 ./http_mcp_examples.sh"
echo ""
echo "MCP JSON-RPC format:"
echo '  {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"TOOL","arguments":{...}}}'
