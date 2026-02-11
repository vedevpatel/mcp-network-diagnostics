"""
SSRF protection for outbound URLs (webhook, notification channels).

Validates that user-supplied URLs resolve to public Internet addresses
and do not target internal infrastructure or cloud metadata endpoints.
"""

import ipaddress
import socket
from urllib.parse import urlparse


# Networks that must never be targets of webhook/notification HTTP requests
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),      # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),     # RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local / cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),          # "This" network
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 unique-local
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]


class SSRFError(ValueError):
    """Raised when a URL fails SSRF validation."""
    pass


def validate_webhook_url(url: str) -> str:
    """Validate a webhook / notification URL against SSRF attacks.

    Returns the canonicalized URL string on success.
    Raises SSRFError if the URL targets a blocked network.
    """
    if not url or not isinstance(url, str):
        raise SSRFError("URL must be a non-empty string")

    parsed = urlparse(url.strip())

    # Require HTTPS (or HTTP for well-known webhook services during dev)
    if parsed.scheme not in ("https", "http"):
        raise SSRFError(f"URL scheme '{parsed.scheme}' not allowed; use https")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("URL has no hostname")

    # Reject hostnames that are IP literals in blocked ranges
    try:
        addr = ipaddress.ip_address(hostname)
        if _is_blocked(addr):
            raise SSRFError(f"URL resolves to blocked address {addr}")
        return url.strip()
    except ValueError:
        # Not an IP literal — resolve via DNS
        pass

    # DNS resolution check
    try:
        results = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise SSRFError(f"Cannot resolve hostname '{hostname}'")

    for family, _type, _proto, _canonname, sockaddr in results:
        addr = ipaddress.ip_address(sockaddr[0])
        if _is_blocked(addr):
            raise SSRFError(
                f"Hostname '{hostname}' resolves to blocked address {addr}"
            )

    return url.strip()


def _is_blocked(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address falls in any blocked network."""
    for network in _BLOCKED_NETWORKS:
        if addr in network:
            return True
    return False
