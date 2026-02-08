"""Edge network collector for consumer-mode diagnostics.

Collects network diagnostics from the user's perspective without requiring
device credentials. Uses standard network tools (ping, traceroute, DNS).

Works on macOS, Linux, and Windows.
"""

import asyncio
import json
import platform
import socket
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse


@dataclass
class GatewayResult:
    """Local gateway ping results."""
    ip: str
    latency_ms: float
    loss_pct: float
    status: str  # "healthy", "degraded", "unreachable"


@dataclass
class DNSResult:
    """DNS resolution timing."""
    hostname: str
    ip: str
    resolution_ms: float
    nameserver: Optional[str] = None


@dataclass
class HopResult:
    """Single hop in traceroute."""
    number: int
    ip: Optional[str]
    hostname: Optional[str]
    latency_ms: float
    loss_pct: float = 0.0
    asn: Optional[str] = None  # Future: AS lookup


@dataclass
class HTTPResult:
    """HTTP timing breakdown."""
    url: str
    dns_ms: float
    connect_ms: float
    tls_ms: float
    ttfb_ms: float  # Time to first byte
    total_ms: float
    status_code: int


@dataclass
class WifiResult:
    """WiFi statistics (platform-specific)."""
    ssid: Optional[str]
    signal_strength_dbm: Optional[int]
    noise_dbm: Optional[int]
    channel: Optional[int]
    quality: str  # "excellent", "good", "fair", "poor"


@dataclass
class ProbeResult:
    """Complete diagnostic probe to a destination."""
    target: str
    gateway: GatewayResult
    dns: Optional[DNSResult]
    traceroute: list[HopResult]
    http: Optional[HTTPResult]
    wifi: Optional[WifiResult]
    timestamp: float = field(default_factory=time.time)


class EdgeCollector:
    """Network diagnostics from user's perspective (no credentials needed)."""

    def __init__(self):
        """Initialize edge collector."""
        self.platform = platform.system()  # Darwin, Linux, Windows

    async def probe_destination(self, target: str) -> ProbeResult:
        """Full diagnostic probe to a destination.

        Args:
            target: URL, hostname, or IP address

        Returns:
            Complete probe results with gateway, DNS, traceroute, HTTP
        """
        # Parse target
        if target.startswith(("http://", "https://")):
            parsed = urlparse(target)
            hostname = parsed.netloc
            is_http = True
        else:
            hostname = target
            is_http = False

        # Run probes in parallel where possible
        gateway_task = self._probe_gateway()
        dns_task = self._probe_dns(hostname) if not self._is_ip(hostname) else None
        traceroute_task = self._run_traceroute(hostname)
        http_task = self._probe_http(target) if is_http else None
        wifi_task = self._get_wifi_stats()

        # Await all tasks
        gateway = await gateway_task
        dns = await dns_task if dns_task else None
        traceroute = await traceroute_task
        http = await http_task if http_task else None
        wifi = await wifi_task

        return ProbeResult(
            target=target,
            gateway=gateway,
            dns=dns,
            traceroute=traceroute,
            http=http,
            wifi=wifi,
        )

    async def _probe_gateway(self) -> GatewayResult:
        """Ping default gateway to measure local network health."""
        gateway_ip = self._get_default_gateway()

        if not gateway_ip:
            return GatewayResult(
                ip="unknown",
                latency_ms=0.0,
                loss_pct=100.0,
                status="unreachable",
            )

        latency, loss = await self._ping(gateway_ip, count=5)

        if loss >= 50.0:
            status = "unreachable"
        elif latency > 10.0 or loss > 5.0:
            status = "degraded"
        else:
            status = "healthy"

        return GatewayResult(
            ip=gateway_ip,
            latency_ms=latency,
            loss_pct=loss,
            status=status,
        )

    async def _probe_dns(self, hostname: str) -> DNSResult:
        """Measure DNS resolution time."""
        start = time.time()
        try:
            ip = socket.gethostbyname(hostname)
            elapsed_ms = (time.time() - start) * 1000
            return DNSResult(
                hostname=hostname,
                ip=ip,
                resolution_ms=elapsed_ms,
            )
        except socket.gaierror:
            return DNSResult(
                hostname=hostname,
                ip="unresolved",
                resolution_ms=-1.0,
            )

    async def _run_traceroute(self, target: str) -> list[HopResult]:
        """Run traceroute and parse results."""
        try:
            if self.platform == "Windows":
                cmd = ["tracert", "-h", "20", "-w", "2000", target]
            else:
                # Try mtr first (better output), fall back to traceroute
                if await self._command_exists("mtr"):
                    cmd = ["mtr", "--report", "--report-cycles", "3", "--json", target]
                else:
                    cmd = ["traceroute", "-m", "20", "-q", "1", target]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=60.0)

            # Parse based on command used
            if "mtr" in cmd[0] and "--json" in cmd:
                return self._parse_mtr_json(stdout.decode())
            elif self.platform == "Windows":
                return self._parse_tracert(stdout.decode())
            else:
                return self._parse_traceroute(stdout.decode())

        except (asyncio.TimeoutError, Exception) as e:
            # Return empty traceroute on failure
            return []

    async def _ping(self, target: str, count: int = 5) -> tuple[float, float]:
        """Ping target and return (avg_latency_ms, loss_pct).

        Returns:
            Tuple of (average latency in ms, packet loss percentage)
        """
        try:
            if self.platform == "Windows":
                cmd = ["ping", "-n", str(count), target]
            else:
                cmd = ["ping", "-c", str(count), target]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            output = stdout.decode()

            return self._parse_ping_output(output)

        except (asyncio.TimeoutError, Exception):
            return (0.0, 100.0)  # Complete failure

    async def _probe_http(self, url: str) -> Optional[HTTPResult]:
        """Measure HTTP timing breakdown using curl."""
        try:
            # Use curl for detailed timing
            cmd = [
                "curl",
                "-w", json.dumps({
                    "dns": "%{time_namelookup}",
                    "connect": "%{time_connect}",
                    "tls": "%{time_appconnect}",
                    "ttfb": "%{time_starttransfer}",
                    "total": "%{time_total}",
                    "code": "%{http_code}",
                }),
                "-o", "/dev/null",
                "-s",
                url,
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30.0)

            timings = json.loads(stdout.decode())

            return HTTPResult(
                url=url,
                dns_ms=float(timings["dns"]) * 1000,
                connect_ms=float(timings["connect"]) * 1000,
                tls_ms=float(timings["tls"]) * 1000 if float(timings["tls"]) > 0 else 0.0,
                ttfb_ms=float(timings["ttfb"]) * 1000,
                total_ms=float(timings["total"]) * 1000,
                status_code=int(timings["code"]),
            )

        except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
            return None

    async def _get_wifi_stats(self) -> Optional[WifiResult]:
        """Get WiFi statistics (platform-specific)."""
        try:
            if self.platform == "Darwin":
                return await self._get_wifi_stats_macos()
            elif self.platform == "Linux":
                return await self._get_wifi_stats_linux()
            elif self.platform == "Windows":
                return await self._get_wifi_stats_windows()
        except Exception:
            pass

        return None

    async def _get_wifi_stats_macos(self) -> Optional[WifiResult]:
        """Get WiFi stats on macOS using airport utility."""
        try:
            cmd = ["/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport", "-I"]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode()

            # Parse airport output
            data = {}
            for line in output.split("\n"):
                if ":" in line:
                    key, value = line.strip().split(":", 1)
                    data[key.strip()] = value.strip()

            ssid = data.get("SSID")
            signal = int(data.get("agrCtlRSSI", "0"))
            noise = int(data.get("agrCtlNoise", "0"))
            channel = int(data.get("channel", "0"))

            # Classify quality based on signal strength
            if signal >= -50:
                quality = "excellent"
            elif signal >= -60:
                quality = "good"
            elif signal >= -70:
                quality = "fair"
            else:
                quality = "poor"

            return WifiResult(
                ssid=ssid,
                signal_strength_dbm=signal,
                noise_dbm=noise,
                channel=channel,
                quality=quality,
            )

        except Exception:
            return None

    async def _get_wifi_stats_linux(self) -> Optional[WifiResult]:
        """Get WiFi stats on Linux using iw or iwconfig."""
        # Implementation placeholder - would use iw/iwconfig parsing
        return None

    async def _get_wifi_stats_windows(self) -> Optional[WifiResult]:
        """Get WiFi stats on Windows using netsh."""
        # Implementation placeholder - would use netsh wlan show interfaces
        return None

    def _get_default_gateway(self) -> Optional[str]:
        """Get default gateway IP address."""
        try:
            if self.platform == "Windows":
                # Use route print on Windows
                result = subprocess.run(
                    ["route", "print", "0.0.0.0"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                # Parse Windows route output
                for line in result.stdout.split("\n"):
                    if "0.0.0.0" in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            return parts[2]
            else:
                # Use ip route or netstat on Unix
                try:
                    result = subprocess.run(
                        ["ip", "route", "show", "default"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    # Parse: default via 192.168.1.1 dev en0
                    parts = result.stdout.split()
                    if "via" in parts:
                        return parts[parts.index("via") + 1]
                except FileNotFoundError:
                    # Fallback to netstat
                    result = subprocess.run(
                        ["netstat", "-rn"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    for line in result.stdout.split("\n"):
                        if line.startswith("default") or line.startswith("0.0.0.0"):
                            parts = line.split()
                            if len(parts) >= 2:
                                return parts[1]

        except (subprocess.TimeoutExpired, Exception):
            pass

        return None

    def _parse_ping_output(self, output: str) -> tuple[float, float]:
        """Parse ping output to extract latency and loss."""
        lines = output.split("\n")

        # Find packet loss line
        loss_pct = 100.0
        for line in lines:
            if "packet loss" in line.lower() or "lost" in line.lower():
                # Extract percentage
                import re
                match = re.search(r'(\d+(?:\.\d+)?)%', line)
                if match:
                    loss_pct = float(match.group(1))
                break

        # Find average latency
        latency_ms = 0.0
        for line in lines:
            if "avg" in line.lower() or "average" in line.lower():
                # Unix: min/avg/max/stddev = 1.234/2.345/3.456/0.123 ms
                # Windows: Average = 12ms
                import re
                if "=" in line:
                    # Windows style
                    match = re.search(r'=\s*(\d+(?:\.\d+)?)ms', line, re.IGNORECASE)
                    if match:
                        latency_ms = float(match.group(1))
                else:
                    # Unix style - look for avg value
                    match = re.search(r'[\d.]+/(\d+(?:\.\d+)?)/[\d.]+', line)
                    if match:
                        latency_ms = float(match.group(1))
                break

        return (latency_ms, loss_pct)

    def _parse_mtr_json(self, output: str) -> list[HopResult]:
        """Parse MTR JSON output."""
        try:
            data = json.loads(output)
            hops = []

            for hop_data in data.get("report", {}).get("hubs", []):
                hops.append(HopResult(
                    number=hop_data.get("count", 0),
                    ip=hop_data.get("host"),
                    hostname=None,
                    latency_ms=hop_data.get("Avg", 0.0),
                    loss_pct=hop_data.get("Loss%", 0.0),
                ))

            return hops
        except (json.JSONDecodeError, KeyError):
            return []

    def _parse_traceroute(self, output: str) -> list[HopResult]:
        """Parse standard traceroute output."""
        hops = []
        import re

        for line in output.split("\n"):
            # Match lines like: " 1  192.168.1.1 (192.168.1.1)  1.234 ms"
            match = re.match(r'\s*(\d+)\s+([^\s]+)\s+\(([^\)]+)\)\s+([\d.]+)\s*ms', line)
            if match:
                hop_num = int(match.group(1))
                hostname = match.group(2)
                ip = match.group(3)
                latency = float(match.group(4))

                hops.append(HopResult(
                    number=hop_num,
                    ip=ip if ip != hostname else None,
                    hostname=hostname if hostname != ip else None,
                    latency_ms=latency,
                ))

        return hops

    def _parse_tracert(self, output: str) -> list[HopResult]:
        """Parse Windows tracert output."""
        hops = []
        import re

        for line in output.split("\n"):
            # Match lines like: "  1    <1 ms    <1 ms    <1 ms  192.168.1.1"
            match = re.match(r'\s*(\d+)\s+(?:<?[\d<]+\s*ms\s*){3}\s+([^\s]+)', line)
            if match:
                hop_num = int(match.group(1))
                ip_or_host = match.group(2)

                # Try to extract latency
                latency_match = re.search(r'(\d+)\s*ms', line)
                latency = float(latency_match.group(1)) if latency_match else 0.0

                hops.append(HopResult(
                    number=hop_num,
                    ip=ip_or_host if self._is_ip(ip_or_host) else None,
                    hostname=ip_or_host if not self._is_ip(ip_or_host) else None,
                    latency_ms=latency,
                ))

        return hops

    def _is_ip(self, value: str) -> bool:
        """Check if value is an IP address."""
        try:
            socket.inet_aton(value)
            return True
        except socket.error:
            return False

    async def _command_exists(self, command: str) -> bool:
        """Check if a command exists in PATH."""
        try:
            if self.platform == "Windows":
                cmd = ["where", command]
            else:
                cmd = ["which", command]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception:
            return False
