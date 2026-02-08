"""Provider status and outage monitoring.

Checks cloud provider status pages and outage databases.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class ProviderStatus:
    """Status for a cloud/network provider."""
    provider: str
    status: str  # "operational", "degraded", "outage"
    incidents: list[str]
    last_checked: datetime


class OutageContext:
    """Cloud provider and network outage context."""

    # Major provider status page APIs (where available)
    PROVIDER_STATUS_URLS = {
        "aws": "https://status.aws.amazon.com/data.json",
        "azure": "https://status.azure.com/en-us/status",
        "cloudflare": "https://www.cloudflarestatus.com/api/v2/status.json",
        "google": "https://status.cloud.google.com/",
    }

    async def check_provider_status(self, provider: str) -> Optional[ProviderStatus]:
        """
        Check if a major cloud provider is experiencing issues.

        Args:
            provider: Provider name (aws, azure, cloudflare, google, etc.)

        Returns:
            ProviderStatus if available, None if provider not supported
        """
        provider = provider.lower()

        # Cloudflare has a nice JSON API
        if provider == "cloudflare":
            return await self._check_cloudflare_status()

        # For others, we'd need to scrape or use unofficial APIs
        # For now, return None (not yet implemented)
        return None

    async def _check_cloudflare_status(self) -> ProviderStatus:
        """Check Cloudflare status page."""
        try:
            # Use curl to fetch status
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "https://www.cloudflarestatus.com/api/v2/status.json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)

            data = json.loads(stdout.decode())
            status_indicator = data.get("status", {}).get("indicator", "unknown")

            # Map status indicator
            status_map = {
                "none": "operational",
                "minor": "degraded",
                "major": "outage",
                "critical": "outage",
            }
            status = status_map.get(status_indicator, "unknown")

            return ProviderStatus(
                provider="cloudflare",
                status=status,
                incidents=[],
                last_checked=datetime.now(timezone.utc),
            )

        except Exception:
            return ProviderStatus(
                provider="cloudflare",
                status="unknown",
                incidents=[],
                last_checked=datetime.now(timezone.utc),
            )

    async def correlate_with_as(self, asn: int) -> Optional[str]:
        """
        Check if an AS number is associated with a known provider having issues.

        Args:
            asn: AS number

        Returns:
            Provider status message if correlated, None otherwise
        """
        # Map common ASNs to providers
        as_to_provider = {
            15169: "google",
            8075: "azure",
            16509: "aws",
            13335: "cloudflare",
        }

        provider = as_to_provider.get(asn)
        if not provider:
            return None

        status = await self.check_provider_status(provider)
        if not status or status.status == "operational":
            return None

        return f"{provider.title()} is experiencing {status.status} (AS{asn})"

    def is_known_provider_as(self, asn: Optional[int]) -> Optional[str]:
        """Check if ASN belongs to a major cloud provider."""
        if asn is None:
            return None

        provider_asns = {
            15169: "Google",
            8075: "Microsoft Azure",
            16509: "Amazon AWS",
            13335: "Cloudflare",
            20940: "Akamai",
            32934: "Facebook",
            2906: "Netflix",
        }

        return provider_asns.get(asn)
