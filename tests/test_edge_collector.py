"""Tests for edge collector (consumer mode diagnostics)."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_network.collectors.edge import EdgeCollector


def _run(coro):
    """Run async coroutine and return result."""
    return asyncio.run(coro)


# Sample command outputs for WiFi parsing tests (realistic formats per OS)
AIRPORT_I_WITH_SSID = """
     agrCtlRSSI: -45
     agrCtlNoise: -92
     state: running
  lastTxRate: 400
     maxRate: 400
lastAssocStatus: 0
     IEEE 802.11: WIFI
  SSID: UCI-WIFI
  BSSID: aa:bb:cc:dd:ee:ff
   channel: 36
"""

AIRPORT_I_NO_SSID = """
     agrCtlRSSI: -54
     agrCtlNoise: -92
     state: running
   channel: 36
"""

NETWORKSETUP_GETAIRPORT = "Current Wi-Fi Network: UCI-WIFI\n"

IW_DEV_LINK = "Connected to aa:bb:cc:dd:ee:ff\nSSID: HomeNetwork\n"
IW_DEV_STATION = "signal: -58 [dBm]\n"

IWCONFIG_OUTPUT = """
wlan0     IEEE 802.11  ESSID:"Office-WiFi"
          Mode:Managed  Frequency:5.18 GHz
          Signal level=-62 dBm
"""

NMCLI_ACTIVE_SSID = "no:Other\nno:Guest\nyes:UCI-WIFI\n"

NETSH_WLAN_INTERFACES = """
There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6 AX201
    SSID                   : UCI-WIFI
    BSSID                  : aa:bb:cc:dd:ee:ff
    Signal                 : 85%
    Channel                : 36
"""


def _make_mock_process(stdout: str, returncode: int = 0):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout.encode("utf-8"), b""))
    return proc


@pytest.mark.no_global_network_mock
class TestEdgeCollector:
    """Test EdgeCollector low-level parsing logic (requires real methods)."""

    def setup_method(self):
        self.collector = EdgeCollector()

    def test_gateway_probe(self):
        """Test gateway probing."""
        # Mock gateway IP and ping response
        with patch.object(self.collector, "_get_default_gateway", return_value="192.168.1.1"), \
             patch.object(self.collector, "_ping", new_callable=AsyncMock) as mock_ping:
            
            mock_ping.return_value = (2.5, 0.0)
            
            result = _run(self.collector._probe_gateway())

            assert result.ip == "192.168.1.1"
            assert result.latency_ms == 2.5
            assert result.loss_pct == 0.0
            assert result.status == "healthy"

    def test_dns_probe(self):
        """Test DNS resolution timing."""
        result = _run(self.collector._probe_dns("google.com"))

        assert result.hostname == "google.com"
        assert result.resolution_ms >= 0.0
        # IP should be resolved or "unresolved"
        assert result.ip is not None

    def test_ping(self):
        """Test ping functionality."""
        # Mock ping execution to avoid system dependencies
        with patch("mcp_network.collectors.edge.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            # Configure mock process output (Linux/Mac style)
            mock_stdout = AsyncMock()
            mock_stdout.communicate.return_value = (
                b"PING 8.8.8.8 (8.8.8.8): 56 data bytes\n"
                b"64 bytes from 8.8.8.8: icmp_seq=0 ttl=117 time=14.2 ms\n"
                b"--- 8.8.8.8 ping statistics ---\n"
                b"3 packets transmitted, 3 packets received, 0.0% packet loss\n"
                b"round-trip min/avg/max/stddev = 12.1/14.5/16.8/2.1 ms\n",
                b""
            )
            mock_proc.return_value.communicate = mock_stdout.communicate
            
            latency, loss = _run(self.collector._ping("8.8.8.8", count=3))

            assert latency == 14.5
            assert loss == 0.0

    def test_traceroute(self):
        """Test traceroute collection."""
        with patch("mcp_network.collectors.edge.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
            mock_stdout = AsyncMock()
            mock_stdout.communicate.return_value = (b"", b"")
            mock_proc.return_value.communicate = mock_stdout.communicate
            
            hops = _run(self.collector._run_traceroute("8.8.8.8"))
            # Should get at least a few hops
            # (may be empty if traceroute/mtr not installed)
            assert isinstance(hops, list)

    def test_probe_destination_basic(self):
        """Test full destination probe."""
        from unittest.mock import patch, AsyncMock
        from mcp_network.collectors.edge import HopResult, DNSResult

        # Use a reliable target
        with patch.object(self.collector, "_get_default_gateway", return_value="192.168.1.1"), \
             patch.object(self.collector, "_ping", new_callable=AsyncMock) as mock_ping, \
             patch.object(self.collector, "_probe_dns", new_callable=AsyncMock) as mock_dns, \
             patch.object(self.collector, "_run_traceroute", new_callable=AsyncMock) as mock_trace:
            
            mock_ping.return_value = (10.0, 0.0)
            mock_trace.return_value = [HopResult(1, "192.168.1.1", "gateway", 2.0, 0.0)]
            mock_dns.return_value = DNSResult("google.com", "8.8.8.8", 10.0)
            
            probe = _run(self.collector.probe_destination("google.com"))

        assert probe.target == "google.com"
        assert probe.gateway is not None
        assert probe.gateway.status in ("healthy", "degraded", "unreachable")

        # DNS should have been probed
        assert probe.dns is not None
        assert probe.dns.hostname == "google.com"

        # Traceroute may be empty if tools not installed
        assert isinstance(probe.traceroute, list)

        assert probe.timestamp > 0


class TestEdgeTools:
    """Tests for edge diagnostic MCP tools."""

    def test_check_my_connection(self):
        """Test connection health check tool."""
        from mcp_network.tools import check_my_connection

        result_json = _run(check_my_connection())
        result = json.loads(result_json)

        assert "overall_status" in result
        assert "layers" in result
        assert "wifi" in result["layers"]
        assert "local_network" in result["layers"]
        assert "dns" in result["layers"]
        assert "internet" in result["layers"]

    def test_trace_path(self):
        """Test trace_path tool."""
        # Use patch to prevent actual network calls
        with patch("mcp_network.collectors.edge.EdgeCollector._run_traceroute", new_callable=AsyncMock) as mock_trace:
            from mcp_network.collectors.edge import HopResult
            mock_trace.return_value = [HopResult(1, "192.168.1.1", "gateway", 2.0, 0.0)]
            
            from mcp_network.tools import trace_path
            result = _run(trace_path("8.8.8.8"))
            assert "hops" in json.loads(result)

    def test_why_is_it_slow(self):
        """Test why_is_it_slow tool."""
        # Mock all the internal calls
        with patch("mcp_network.collectors.edge.EdgeCollector._ping", new_callable=AsyncMock) as mock_ping, \
             patch("mcp_network.collectors.edge.EdgeCollector._run_traceroute", new_callable=AsyncMock) as mock_trace, \
             patch("mcp_network.collectors.edge.EdgeCollector._get_default_gateway", return_value="192.168.1.1"), \
             patch("mcp_network.collectors.edge.EdgeCollector.scan_local_network", new_callable=AsyncMock) as mock_scan:
            
            mock_ping.return_value = (10.0, 0.0)
            mock_trace.return_value = []
            mock_scan.return_value = []
            
            from mcp_network.tools import why_is_it_slow
            result_json = _run(why_is_it_slow("google.com"))
            result = json.loads(result_json)

            assert "destination" in result
            assert result["destination"] == "google.com"

            # Should have diagnosis or error
            assert "diagnosis" in result or "error" in result

            if "diagnosis" in result:
                assert "bottleneck" in result["diagnosis"]
                assert "confidence" in result["diagnosis"]
                assert "suggestions" in result


@pytest.mark.no_global_network_mock
class TestWifiDetectionPerOS:
    """Test Wi-Fi parsing logic per OS (requires real methods)."""

    @pytest.mark.asyncio
    async def test_macos_airport_parses_ssid(self):
        """macOS: airport -I with SSID in output returns correct WifiResult."""
        with patch("platform.system", return_value="Darwin"):
            collector = EdgeCollector()
            with patch(
                "mcp_network.collectors.edge.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                side_effect=lambda *args, **kwargs: _make_mock_process(AIRPORT_I_WITH_SSID),
            ):
                result = await collector._get_wifi_stats()
        assert result is not None
        assert result.ssid == "UCI-WIFI"
        assert result.signal_strength_dbm == -45
        assert result.quality == "excellent"

    @pytest.mark.asyncio
    async def test_macos_networksetup_fallback_parses_ssid(self):
        """macOS: when airport has no SSID, networksetup/ipconfig fallback can supply SSID."""
        calls = []

        def choose_output(*args, **kwargs):
            cmd_parts = [a for a in args if isinstance(a, str)]
            cmd_str = " ".join(cmd_parts)
            calls.append(cmd_str)
            if "airport" in cmd_str:
                return _make_mock_process(AIRPORT_I_NO_SSID)
            if "listallhardwareports" in cmd_str:
                return _make_mock_process(
                    "Hardware Port: Wi-Fi\nDevice: en0\nEthernet Address: aa:bb:cc:dd:ee:ff\n"
                )
            if "getairportnetwork" in cmd_str:
                return _make_mock_process(NETWORKSETUP_GETAIRPORT)
            if "ipconfig" in cmd_str:
                return _make_mock_process("")
            return _make_mock_process("")

        with patch("platform.system", return_value="Darwin"):
            collector = EdgeCollector()
            with patch(
                "mcp_network.collectors.edge.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                side_effect=choose_output,
            ):
                result = await collector._get_wifi_stats()
        assert result is not None
        assert result.signal_strength_dbm == -54
        # Fallback path should have been tried (listallhardwareports and/or getairportnetwork)
        assert any("listallhardwareports" in c or "getairportnetwork" in c for c in calls)
        # When fallback mock returns SSID, we should see it
        if result.ssid is not None:
            assert result.ssid == "UCI-WIFI"

    @pytest.mark.asyncio
    async def test_linux_iw_parses_ssid_and_signal(self):
        """Linux: iw dev/link/station output parses SSID and signal."""
        def choose_output(*args, **kwargs):
            cmd_parts = [a for a in args if isinstance(a, str)]
            c = " ".join(cmd_parts)
            if c == "iw dev":
                return _make_mock_process("phy#0\n\tInterface wlan0\n")
            if "link" in c and "station" not in c:
                return _make_mock_process(IW_DEV_LINK)
            if "station" in c:
                return _make_mock_process(IW_DEV_STATION)
            return _make_mock_process("")

        async def command_exists(cmd):
            return cmd == "iw"

        with patch("platform.system", return_value="Linux"):
            collector = EdgeCollector()
            with patch(
                "mcp_network.collectors.edge.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                side_effect=choose_output,
            ):
                with patch.object(
                    collector, "_command_exists", side_effect=command_exists
                ):
                    result = await collector._get_wifi_stats()
        assert result is not None
        assert result.ssid == "HomeNetwork"
        assert result.signal_strength_dbm == -58
        assert result.quality == "good"

    @pytest.mark.asyncio
    async def test_linux_iwconfig_parses_essid(self):
        """Linux: iwconfig fallback parses ESSID and signal."""
        async def command_exists(cmd):
            return cmd == "iwconfig"

        def choose_output(*args, **kwargs):
            cmd_parts = [a for a in args if isinstance(a, str)]
            c = " ".join(cmd_parts)
            if "iwconfig" in c:
                return _make_mock_process(IWCONFIG_OUTPUT)
            return _make_mock_process("")

        with patch("platform.system", return_value="Linux"):
            collector = EdgeCollector()
            with patch(
                "mcp_network.collectors.edge.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                side_effect=choose_output,
            ):
                with patch.object(
                    collector, "_command_exists", side_effect=command_exists
                ):
                    result = await collector._get_wifi_stats()
        assert result is not None
        assert result.ssid == "Office-WiFi"
        assert result.signal_strength_dbm == -62

    @pytest.mark.asyncio
    async def test_linux_nmcli_fallback_parses_ssid(self):
        """Linux: nmcli fallback returns active SSID when iw doesn't report it."""
        async def command_exists(cmd):
            return cmd in ("iw", "nmcli")

        def choose_output(*args, **kwargs):
            cmd_parts = [a for a in args if isinstance(a, str)]
            c = " ".join(cmd_parts)
            if c == "iw dev":
                return _make_mock_process("phy#0\n\tInterface wlan0\n")
            if "link" in c and "station" not in c:
                return _make_mock_process("Connected to aa:bb\n")  # no SSID in link
            if "station" in c:
                return _make_mock_process("signal: -55\n")
            if "nmcli" in c:
                return _make_mock_process(NMCLI_ACTIVE_SSID)
            return _make_mock_process("")

        with patch("platform.system", return_value="Linux"):
            collector = EdgeCollector()
            with patch(
                "mcp_network.collectors.edge.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                side_effect=choose_output,
            ):
                with patch.object(
                    collector, "_command_exists", side_effect=command_exists
                ):
                    result = await collector._get_wifi_stats()
        assert result is not None
        assert result.ssid == "UCI-WIFI"

    @pytest.mark.asyncio
    async def test_windows_netsh_parses_ssid_and_signal(self):
        """Windows: netsh wlan show interfaces parses SSID and signal."""
        with patch("platform.system", return_value="Windows"):
            collector = EdgeCollector()
            with patch(
                "mcp_network.collectors.edge.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                side_effect=lambda *args, **kwargs: _make_mock_process(NETSH_WLAN_INTERFACES),
            ):
                result = await collector._get_wifi_stats()
        assert result is not None
        assert result.ssid == "UCI-WIFI"
        assert result.signal_strength_dbm is not None
        assert result.quality in ("excellent", "good", "fair", "poor")

    @pytest.mark.asyncio
    async def test_unknown_platform_returns_none(self):
        """Non-Darwin/Linux/Windows returns None for WiFi stats."""
        with patch("platform.system", return_value="FreeBSD"):
            collector = EdgeCollector()
            result = await collector._get_wifi_stats()
        assert result is None


@pytest.mark.no_global_network_mock
class TestScanLocalNetwork:
    """Test local network scanning logic (requires real methods)."""

    def test_parse_arp_macos(self):
        """Parse macOS arp -a output."""
        from mcp_network.collectors.edge import EdgeCollector

        collector = EdgeCollector()
        output = """
? (192.168.1.1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]
router.local (192.168.1.5) at 11:22:33:44:55:66 on en0 ifscope [ethernet]
"""
        result = collector._parse_arp_macos(output)
        assert len(result) == 2
        assert result[0] == ("192.168.1.1", "aa:bb:cc:dd:ee:ff", None)
        assert result[1] == ("192.168.1.5", "11:22:33:44:55:66", "router.local")

    def test_parse_arp_linux_ip_neigh(self):
        """Parse Linux ip neigh show output."""
        from mcp_network.collectors.edge import EdgeCollector

        collector = EdgeCollector()
        output = """
192.168.1.1 lladdr aa:bb:cc:dd:ee:ff REACHABLE
192.168.1.10 lladdr 11:22:33:44:55:66 STALE
"""
        result = collector._parse_arp_linux_ip_neigh(output)
        assert len(result) == 2
        assert result[0] == ("192.168.1.1", "aa:bb:cc:dd:ee:ff", None)
        assert result[1] == ("192.168.1.10", "11:22:33:44:55:66", None)

    def test_parse_arp_windows(self):
        """Parse Windows arp -a output."""
        from mcp_network.collectors.edge import EdgeCollector

        collector = EdgeCollector()
        output = """
Interface: 192.168.1.100 --- 0xc
  Internet Address      Physical Address      Type
  192.168.1.1           aa-bb-cc-dd-ee-ff     dynamic
  192.168.1.5           11-22-33-44-55-66     dynamic
"""
        result = collector._parse_arp_windows(output)
        assert len(result) == 2
        assert result[0] == ("192.168.1.1", "aa:bb:cc:dd:ee:ff", None)
        assert result[1] == ("192.168.1.5", "11:22:33:44:55:66", None)

    def test_scan_local_network_returns_devices(self):
        """scan_local_network returns sorted list of LocalDevice (mocked ARP)."""
        from mcp_network.collectors.edge import EdgeCollector, LocalDevice

        collector = EdgeCollector()
        with patch.object(collector, "_get_arp_table", new_callable=AsyncMock) as mock_arp:
            mock_arp.return_value = [
                ("192.168.1.5", "11:22:33:44:55:66", None),
                ("192.168.1.1", "aa:bb:cc:dd:ee:ff", "router"),
            ]
            with patch.object(collector, "_get_default_gateway", return_value="192.168.1.1"):
                devices = _run(collector.scan_local_network())

        assert len(devices) == 2
        assert all(isinstance(d, LocalDevice) for d in devices)
        assert devices[0].ip == "192.168.1.1"
        assert devices[1].ip == "192.168.1.5"
        assert devices[0].mac == "aa:bb:cc:dd:ee:ff"
        assert devices[0].hostname == "router"
