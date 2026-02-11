"""BGP and AS number lookup for hop enrichment.

Uses Team Cymru's IP to ASN mapping service (DNS-based, free, no auth required).
"""

import asyncio
from dataclasses import dataclass
import logging
from typing import Optional


_session_logger = logging.getLogger(__name__)


@dataclass
class ASInfo:
    """Autonomous System information for an IP."""
    ip: str
    asn: Optional[int]
    as_name: Optional[str]
    country: Optional[str]
    registry: Optional[str]  # ARIN, RIPE, APNIC, etc.


class BGPContext:
    """BGP routing and AS number context provider."""

    async def get_as_info(self, ip: str) -> ASInfo:
        """
        Lookup AS number and organization for an IP address.

        Uses Team Cymru's IP to ASN DNS service:
        https://www.team-cymru.com/ip-asn-mapping

        Args:
            ip: IP address to lookup

        Returns:
            ASInfo with ASN and organization name
        """
        try:
            # Team Cymru DNS lookup format: reverse-ip.origin.asn.cymru.com
            # Example: 8.8.8.8 -> 8.8.8.8.origin.asn.cymru.com
            reversed_ip = ".".join(reversed(ip.split(".")))
            query_domain = f"{reversed_ip}.origin.asn.cymru.com"

            # DNS TXT query
            # The original code had a commented-out section using socket.gethostbyname_ex
            # which is not suitable for TXT records.
            # The current implementation uses subprocess 'host' command.

            # Let's use a simpler approach with subprocess dig/host
            proc = await asyncio.create_subprocess_exec(
                "host", "-t", "TXT", query_domain,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode()

            # Parse output: "TXT record: \"ASN | IP | Registry | Allocated | AS Name\""
            if "\"" in output:
                txt_record = output.split("\"")[1]
                parts = [p.strip() for p in txt_record.split("|")]

                if len(parts) >= 5:
                    asn = int(parts[0]) if parts[0].isdigit() else None
                    registry = parts[2] if len(parts) > 2 else None
                    country = parts[3] if len(parts) > 3 else None
                    as_name = parts[4] if len(parts) > 4 else None

                    return ASInfo(
                        ip=ip,
                        asn=asn,
                        as_name=as_name,
                        country=country,
                        registry=registry,
                    )

        except Exception:
            pass

        # Fallback - return unknown
        return ASInfo(
            ip=ip,
            asn=None,
            as_name="Unknown",
            country=None,
            registry=None,
        )

    def format_as_info(self, as_info: ASInfo) -> str:
        """Format AS info for human consumption."""
        if as_info.asn is None:
            return f"{as_info.ip} (Unknown network)"

        parts = [f"AS{as_info.asn}"]
        if as_info.as_name:
            parts.append(as_info.as_name)
        if as_info.country:
            parts.append(as_info.country.upper())

        return f"{as_info.ip} ({' - '.join(parts)})"
