#!/bin/bash
# Comprehensive curl tests for consumer/edge dashboard
# Run this while the dashboard is running: uv run python -m mcp_network.dashboard

BASE_URL="${BASE_URL:-http://localhost:8080}"
COOKIE_JAR=$(mktemp)
echo "Testing dashboard at $BASE_URL"
echo "Cookie jar: $COOKIE_JAR"
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

test_name() {
    echo -e "\n${YELLOW}=== $1 ===${NC}"
}

check_status() {
    local expected=$1
    local actual=$2
    local name=$3
    if [ "$actual" -eq "$expected" ]; then
        echo -e "${GREEN}✓${NC} $name: $actual"
        return 0
    else
        echo -e "${RED}✗${NC} $name: expected $expected, got $actual"
        return 1
    fi
}

# ============================================================================
# 1. Basic Page Loads
# ============================================================================
test_name "Basic Page Loads"

echo "GET /"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -c "$COOKIE_JAR" "$BASE_URL/")
check_status 200 "$STATUS" "Overview page"

echo "GET /tools"
STATUS=$(curl -s -L -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" "$BASE_URL/tools")
check_status 200 "$STATUS" "Tools page"

echo "GET /settings"
STATUS=$(curl -s -L -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" "$BASE_URL/settings")
check_status 200 "$STATUS" "Settings page"

echo "GET /static/style.css"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" "$BASE_URL/static/style.css")
check_status 200 "$STATUS" "Static CSS"

# ============================================================================
# 2. Connection Partial (HTMX endpoint)
# ============================================================================
test_name "Connection Partial (HTMX)"

echo "GET /partials/connection"
RESPONSE=$(curl -s -b "$COOKIE_JAR" "$BASE_URL/partials/connection")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" "$BASE_URL/partials/connection")
check_status 200 "$STATUS" "Connection partial"

if echo "$RESPONSE" | grep -q "My Connection"; then
    echo -e "${GREEN}✓${NC} Contains 'My Connection'"
else
    echo -e "${RED}✗${NC} Missing 'My Connection'"
fi

if echo "$RESPONSE" | grep -q "WiFi\|Local Network\|DNS\|Internet"; then
    echo -e "${GREEN}✓${NC} Contains connection cards"
else
    echo -e "${RED}✗${NC} Missing connection cards"
fi

# ============================================================================
# 3. Consumer Tools - Valid Invocations
# ============================================================================
test_name "Consumer Tools - Valid Invocations"

echo "POST /tools/invoke - check_my_connection"
RESPONSE=$(curl -s -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=check_my_connection")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=check_my_connection")
check_status 200 "$STATUS" "check_my_connection"

if echo "$RESPONSE" | grep -q "overall_status\|layers"; then
    echo -e "${GREEN}✓${NC} Valid JSON response"
else
    echo -e "${YELLOW}⚠${NC} Response may not be JSON (could be HTML fragment)"
fi

echo "POST /tools/invoke - scan_local_network"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=scan_local_network")
check_status 200 "$STATUS" "scan_local_network"

echo "POST /tools/invoke - trace_path with destination"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=trace_path" \
    -F "destination=8.8.8.8")
check_status 200 "$STATUS" "trace_path(8.8.8.8)"

echo "POST /tools/invoke - why_is_it_slow"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=why_is_it_slow" \
    -F "destination=google.com")
check_status 200 "$STATUS" "why_is_it_slow(google.com)"

echo "POST /tools/invoke - record_baseline"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=record_baseline")
check_status 200 "$STATUS" "record_baseline"

# ============================================================================
# 4. Edge Cases - Invalid Inputs
# ============================================================================
test_name "Edge Cases - Invalid Inputs"

echo "POST /tools/invoke - missing tool_id"
RESPONSE=$(curl -s -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke")
check_status 200 "$STATUS" "Missing tool_id (should return error fragment)"
if echo "$RESPONSE" | grep -qi "missing\|error"; then
    echo -e "${GREEN}✓${NC} Error message present"
fi

echo "POST /tools/invoke - unknown tool_id"
RESPONSE=$(curl -s -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=nonexistent_tool_xyz")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=nonexistent_tool_xyz")
check_status 200 "$STATUS" "Unknown tool_id"
if echo "$RESPONSE" | grep -qi "unknown\|not found"; then
    echo -e "${GREEN}✓${NC} Error message present"
fi

echo "POST /tools/invoke - trace_path with empty destination"
RESPONSE=$(curl -s -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=trace_path" \
    -F "destination=")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=trace_path" \
    -F "destination=")
# May succeed (tool handles empty) or fail validation
echo -e "${YELLOW}⚠${NC} Empty destination: status $STATUS"

echo "POST /tools/invoke - trace_path with invalid destination (SSRF attempt?)"
RESPONSE=$(curl -s -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=trace_path" \
    -F "destination=file:///etc/passwd")
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=trace_path" \
    -F "destination=file:///etc/passwd")
# Should be rejected by validation
if [ "$STATUS" -eq 200 ]; then
    if echo "$RESPONSE" | grep -qi "invalid\|not allowed\|validation"; then
        echo -e "${GREEN}✓${NC} Invalid destination rejected"
    else
        echo -e "${RED}✗${NC} Invalid destination not rejected"
    fi
else
    echo -e "${GREEN}✓${NC} Invalid destination rejected (status $STATUS)"
fi

# ============================================================================
# 5. Rate Limiting
# ============================================================================
test_name "Rate Limiting (60 req/min default)"

echo "Burst requests to /partials/connection (should hit rate limit)"
echo "Sending 70 requests rapidly to exhaust token bucket..."
RATE_LIMITED=0
START_TIME=$(date +%s)
for i in {1..70}; do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" "$BASE_URL/partials/connection" 2>/dev/null)
    if [ "$STATUS" -eq 429 ]; then
        RATE_LIMITED=1
        ELAPSED=$(($(date +%s) - START_TIME))
        echo -e "${GREEN}✓${NC} Rate limited at request $i after ${ELAPSED}s (status 429)"
        break
    fi
    # No sleep - send as fast as possible to exhaust bucket before refill
done

if [ "$RATE_LIMITED" -eq 0 ]; then
    ELAPSED=$(($(date +%s) - START_TIME))
    echo -e "${YELLOW}⚠${NC} Rate limit not hit after 70 requests in ${ELAPSED}s"
    echo -e "${YELLOW}  ${NC} Token bucket refills at 1 token/sec, so requests must be faster than that"
    echo -e "${YELLOW}  ${NC} Try: CONSUMER_RATE_LIMIT_PER_MINUTE=10 ./test_dashboard_curl.sh for faster test"
fi

# ============================================================================
# 6. Guest Session Behavior
# ============================================================================
test_name "Guest Session Behavior"

echo "First request (should set session cookie)"
RESPONSE=$(curl -s -c "$COOKIE_JAR" "$BASE_URL/")
if grep -q "mcp_consumer_session" "$COOKIE_JAR"; then
    echo -e "${GREEN}✓${NC} Session cookie set"
else
    echo -e "${RED}✗${NC} Session cookie not set"
fi

echo "Second request (should show 'Using as guest')"
RESPONSE=$(curl -s -b "$COOKIE_JAR" "$BASE_URL/")
if echo "$RESPONSE" | grep -q "Using as guest"; then
    echo -e "${GREEN}✓${NC} 'Using as guest' shown"
else
    echo -e "${YELLOW}⚠${NC} 'Using as guest' not found (may be in header)"
fi

# ============================================================================
# 7. Concurrent Requests (Session Isolation)
# ============================================================================
test_name "Session Isolation"

COOKIE_JAR2=$(mktemp)
echo "Request 1 with session A"
curl -s -c "$COOKIE_JAR" "$BASE_URL/" > /dev/null

echo "Request 2 with session B (new cookie jar)"
curl -s -c "$COOKIE_JAR2" "$BASE_URL/" > /dev/null

if ! diff -q "$COOKIE_JAR" "$COOKIE_JAR2" > /dev/null; then
    echo -e "${GREEN}✓${NC} Different sessions get different cookies"
else
    echo -e "${RED}✗${NC} Sessions share cookies (should be isolated)"
fi
rm "$COOKIE_JAR2"

# ============================================================================
# 8. Error Handling
# ============================================================================
test_name "Error Handling"

echo "GET /nonexistent"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" "$BASE_URL/nonexistent")
check_status 404 "$STATUS" "Nonexistent route"

echo "POST /tools/invoke with malformed form"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "invalid=form&data")
# May return 200 with error fragment or 400
echo -e "${YELLOW}⚠${NC} Malformed form: status $STATUS"

# ============================================================================
# 9. Tool Output Format
# ============================================================================
test_name "Tool Output Format"

echo "POST /tools/invoke - check_my_connection (check response format)"
RESPONSE=$(curl -s -b "$COOKIE_JAR" -X POST "$BASE_URL/tools/invoke" \
    -F "tool_id=check_my_connection")
# Should be HTML fragment (pre tag) or JSON
if echo "$RESPONSE" | grep -q "<pre\|tool-output"; then
    echo -e "${GREEN}✓${NC} HTML fragment format"
elif echo "$RESPONSE" | grep -q "{"; then
    echo -e "${GREEN}✓${NC} JSON format"
else
    echo -e "${YELLOW}⚠${NC} Unexpected format"
fi

# ============================================================================
# Summary
# ============================================================================
echo ""
echo -e "${YELLOW}=== Test Summary ===${NC}"
echo "Cookie jar saved at: $COOKIE_JAR"
echo "Run: cat $COOKIE_JAR to see session cookies"
echo ""
echo "To test with different rate limit:"
echo "  CONSUMER_RATE_LIMIT_PER_MINUTE=10 $0"
echo ""
echo "To test with different base URL:"
echo "  BASE_URL=http://localhost:8080 $0"
