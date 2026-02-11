import pytest
from unittest.mock import AsyncMock, patch
from mcp_network.collectors.edge import HopResult, DNSResult

@pytest.fixture(autouse=True)
def mock_edge_collector_network_calls(request):
    """Globally mock EdgeCollector network calls to prevent CI hangs.
    
    Can be disabled for specific tests using @pytest.mark.no_global_network_mock
    """
    if request.node.get_closest_marker("no_global_network_mock"):
        # Still need to patch security mode for these tests
        with patch("mcp_network.security.tool_guard._STDIO_MODE", "full"):
            yield
        return

    with patch("mcp_network.security.tool_guard._STDIO_MODE", "full"), \
         patch("mcp_network.collectors.edge.EdgeCollector._get_default_gateway", return_value="192.168.1.1"), \
         patch("mcp_network.collectors.edge.EdgeCollector._ping", new_callable=AsyncMock) as mock_ping, \
         patch("mcp_network.collectors.edge.EdgeCollector._probe_dns", new_callable=AsyncMock) as mock_dns, \
         patch("mcp_network.collectors.edge.EdgeCollector._run_traceroute", new_callable=AsyncMock) as mock_trace, \
         patch("mcp_network.collectors.edge.EdgeCollector._get_wifi_stats", new_callable=AsyncMock) as mock_wifi, \
         patch("mcp_network.collectors.edge.EdgeCollector.scan_local_network", new_callable=AsyncMock) as mock_scan:
        
        # Setup default return values
        mock_ping.return_value = (10.0, 0.0)
        mock_dns.return_value = DNSResult("google.com", "8.8.8.8", 10.0)
        mock_trace.return_value = [HopResult(1, "192.168.1.1", "gateway", 2.0, 0.0)]
        mock_wifi.return_value = None
        mock_scan.return_value = []
        
        yield
