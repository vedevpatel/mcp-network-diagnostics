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

            # Parse airport output (keys may have leading/trailing spaces)
            data = {}
            for line in output.split("\n"):
                if ":" in line:
                    key, value = line.strip().split(":", 1)
                    data[key.strip()] = value.strip()

            # SSID: try exact keys first, then any key that normalizes to "ssid"
            ssid = data.get("SSID") or data.get(" SSID")
            if not ssid:
                for k, v in data.items():
                    if k.strip().lower() == "ssid" and isinstance(v, str) and v.strip():
                        ssid = v.strip()
                        break
            if not ssid:
                # Scan raw lines (handles odd spacing/encoding in airport -I)
                for line in output.split("\n"):
                    if "SSID" in line and ":" in line:
                        after = line.split(":", 1)[1].strip()
                        if after and after.lower() not in ("n/a", "unknown", "none"):
                            ssid = after
                            break
            if isinstance(ssid, str):
                ssid = ssid.strip() or None
            else:
                ssid = None

            # If airport didn't report SSID, try networksetup + ipconfig (e.g. permission or newer macOS)
            if not ssid:
                ssid = await self._get_ssid_networksetup_macos()

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

    async def _get_wifi_interface_macos(self) -> list[str]:
        """Discover Wi-Fi interface name(s) via networksetup -listallhardwareports."""
        interfaces = []
        try:
            proc = await asyncio.create_subprocess_exec(
                "/usr/sbin/networksetup", "-listallhardwareports",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return ["en0", "en1"]  # fallback order
            lines = stdout.decode().split("\n")
            current_port = None
            for line in lines:
                if "Hardware Port:" in line:
                    port = line.split("Hardware Port:")[1].strip().lower()
                    current_port = "wi-fi" in port or "wifi" in port or "airport" in port
                elif current_port and "Device:" in line:
                    device = line.split("Device:")[1].strip()
                    if device:
                        interfaces.append(device)
                    current_port = False
            if interfaces:
                return interfaces
        except Exception:
            pass
        return ["en0", "en1"]

    async def _get_ssid_networksetup_macos(self) -> Optional[str]:
        """Fallback: get current WiFi SSID via networksetup or ipconfig (works when airport -I omits SSID)."""
        interfaces = await self._get_wifi_interface_macos()
        for interface in interfaces:
            # 1) networksetup (full path so it works when PATH is minimal under uv/launchd)
            try:
                proc = await asyncio.create_subprocess_exec(
                    "/usr/sbin/networksetup", "-getairportnetwork", interface,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0:
                    line = stdout.decode().strip()
                    if "Current " in line and " Network:" in line and ":" in line:
                        ssid = line.split(":", 1)[1].strip()
                        if ssid and "not associated" not in ssid.lower():
                            return ssid
            except Exception:
                pass

            # 2) ipconfig getsummary (reliable when networksetup fails; use full path for uv/restricted PATH)
            try:
                proc = await asyncio.create_subprocess_exec(
                    "/usr/sbin/ipconfig", "getsummary", interface,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0:
                    for line in stdout.decode().split("\n"):
                        if "SSID" in line and "redact" not in line.lower():
                            # " SSID : UCI-WIFI" or "SSID: UCI-WIFI"
                            after = line.split(":", 1)[1].strip() if ":" in line else line.split("SSID", 1)[-1].strip()
                            if after and after.lower() not in ("n/a", "unknown", "none", "<redacted>"):
                                return after
            except Exception:
                pass
        return None

    async def _get_wifi_stats_linux(self) -> Optional[WifiResult]:
        """Get WiFi stats on Linux using iw or iwconfig."""
        try:
            # Try iw first (modern approach)
            if await self._command_exists("iw"):
                # Find wireless interface
                proc = await asyncio.create_subprocess_exec(
                    "iw", "dev",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                output = stdout.decode()

                # Extract interface name (e.g., wlan0, wlp2s0)
                interface = None
                for line in output.split("\n"):
                    if "Interface" in line:
                        interface = line.split()[1]
                        break

                if not interface:
                    return None

                # Get link info
                proc = await asyncio.create_subprocess_exec(
                    "iw", "dev", interface, "link",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                link_output = stdout.decode()

                # Get station info for signal strength
                proc = await asyncio.create_subprocess_exec(
                    "iw", "dev", interface, "station", "dump",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                station_output = stdout.decode()

                # Parse output
                ssid = None
                signal = None

                for line in link_output.split("\n"):
                    if "SSID:" in line:
                        raw_ssid = line.split("SSID:")[1].strip()
                        if raw_ssid and raw_ssid != "off/any":
                            ssid = raw_ssid

                # If iw didn't report SSID, try nmcli (NetworkManager) as fallback
                if not ssid and await self._command_exists("nmcli"):
                    nmcli_ssid = await self._get_ssid_nmcli_linux()
                    if nmcli_ssid:
                        ssid = nmcli_ssid

                for line in station_output.split("\n"):
                    if "signal:" in line:
                        # Format: "signal: -52 dBm"
                        parts = line.split()
                        if len(parts) >= 2:
                            signal = int(parts[1])

                if signal is None:
                    return None

                # Classify quality
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
                    noise_dbm=None,
                    channel=None,
                    quality=quality,
                )

            # Fallback to iwconfig (older systems)
            elif await self._command_exists("iwconfig"):
                proc = await asyncio.create_subprocess_exec(
                    "iwconfig",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                output = stdout.decode()

                # Parse iwconfig output
                ssid = None
                signal = None

                for line in output.split("\n"):
                    if "ESSID:" in line:
                        # Format: ESSID:"NetworkName"
                        parts = line.split("ESSID:")
                        if len(parts) > 1:
                            raw = parts[1].strip().strip('"')
                            if raw and raw != "off/any":
                                ssid = raw

                    if "Signal level=" in line:
                        # Format: Signal level=-52 dBm
                        import re
                        match = re.search(r'Signal level=(-?\d+)', line)
                        if match:
                            signal = int(match.group(1))

                if signal is None:
                    return None

                # Classify quality
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
                    noise_dbm=None,
                    channel=None,
                    quality=quality,
                )

        except Exception:
            pass

        return None

    async def _get_wifi_stats_windows(self) -> Optional[WifiResult]:
        """Get WiFi stats on Windows using netsh."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "netsh", "wlan", "show", "interfaces",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode()

            # Parse netsh output
            ssid = None
            signal = None
            channel = None

            for line in output.split("\n"):
                line = line.strip()

                if "SSID" in line and ":" in line and "BSSID" not in line:
                    ssid = line.split(":", 1)[1].strip()

                if "Signal" in line and ":" in line:
                    # Format: "Signal                 : 85%"
                    signal_str = line.split(":", 1)[1].strip().rstrip("%")
                    try:
                        signal_pct = int(signal_str)
                        # Convert percentage to dBm (approximate)
                        # 100% = -30 dBm, 0% = -90 dBm
                        signal = -90 + (signal_pct * 0.6)
                    except ValueError:
                        pass

                if "Channel" in line and ":" in line:
                    try:
                        channel = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass

            if signal is None:
                return None

            # Classify quality based on dBm
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
                signal_strength_dbm=int(signal),
                noise_dbm=None,
                channel=channel,
                quality=quality,
            )

        except Exception:
            pass

        return None

    async def _get_ssid_nmcli_linux(self) -> Optional[str]:
        """Get active WiFi SSID via NetworkManager (nmcli). Used as fallback when iw/iwconfig don't report SSID."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "nmcli", "-t", "-f", "active,ssid", "dev", "wifi",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return None
            for line in stdout.decode().strip().split("\n"):
                # Format: yes:MyNetworkName or no:OtherNetwork
                if line.startswith("yes:"):
                    ssid = line.split(":", 1)[1].strip()
                    return ssid if ssid else None
        except Exception:
            pass
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
            line = line.strip()

            # Skip header/footer lines
            if not line or "Tracing route" in line or "Trace complete" in line:
                continue

            # Match lines like: "  1    <1 ms    <1 ms    <1 ms  192.168.1.1"
            # Or: "  2    10 ms     9 ms    11 ms  router.example.com [10.0.0.1]"
            # Or: "  3     *        *        *     Request timed out."

            hop_match = re.match(r'\s*(\d+)\s+', line)
            if not hop_match:
                continue

            hop_num = int(hop_match.group(1))

            # Check for timeout
            if "Request timed out" in line or "*" in line:
                hops.append(HopResult(
                    number=hop_num,
                    ip=None,
                    hostname="*",
                    latency_ms=0.0,
                    loss_pct=100.0,
                ))
                continue

            # Extract latency (average of the three values)
            latency_values = re.findall(r'(\d+)\s*ms', line)
            if latency_values:
                latency = sum(int(v) for v in latency_values) / len(latency_values)
            else:
                latency = 0.0

            # Extract hostname and IP
            # Format: "hostname [ip]" or just "ip" or just "hostname"
            bracket_match = re.search(r'([^\s\[]+)\s+\[([^\]]+)\]', line)
            if bracket_match:
                hostname = bracket_match.group(1)
                ip = bracket_match.group(2)
            else:
                # No brackets - extract last token
                tokens = line.split()
                last_token = tokens[-1] if tokens else ""
                if self._is_ip(last_token):
                    hostname = None
                    ip = last_token
                else:
                    hostname = last_token
                    ip = None

            hops.append(HopResult(
                number=hop_num,
                ip=ip if ip and self._is_ip(ip) else None,
                hostname=hostname if hostname and hostname != ip else None,
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
