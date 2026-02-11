"""Tests for SSRF protection (ssrf.py)."""

import pytest
from unittest.mock import patch

from mcp_network.security.ssrf import validate_webhook_url, SSRFError


class TestSSRFValidation:
    """Test URL validation against SSRF attacks."""

    # -----------------------------------------------------------------------
    # Blocked URLs
    # -----------------------------------------------------------------------

    def test_loopback_ipv4_blocked(self):
        """Loopback 127.0.0.1 is blocked."""
        with pytest.raises(SSRFError, match="blocked"):
            validate_webhook_url("http://127.0.0.1/webhook")

    def test_loopback_ipv4_variant_blocked(self):
        """Loopback 127.0.0.42 is blocked."""
        with pytest.raises(SSRFError, match="blocked"):
            validate_webhook_url("http://127.0.0.42:8080/hook")

    def test_private_10_network_blocked(self):
        """RFC 1918 10.x.x.x is blocked."""
        with pytest.raises(SSRFError, match="blocked"):
            validate_webhook_url("http://10.0.0.1:9090/alert")

    def test_private_172_network_blocked(self):
        """RFC 1918 172.16.x.x is blocked."""
        with pytest.raises(SSRFError, match="blocked"):
            validate_webhook_url("http://172.16.0.1/webhook")

    def test_private_192_168_blocked(self):
        """RFC 1918 192.168.x.x is blocked."""
        with pytest.raises(SSRFError, match="blocked"):
            validate_webhook_url("http://192.168.1.1/alert")

    def test_cloud_metadata_blocked(self):
        """AWS/GCP metadata endpoint 169.254.169.254 is blocked."""
        with pytest.raises(SSRFError, match="blocked"):
            validate_webhook_url("http://169.254.169.254/latest/meta-data/")

    def test_zero_network_blocked(self):
        """0.0.0.0 is blocked."""
        with pytest.raises(SSRFError, match="blocked"):
            validate_webhook_url("http://0.0.0.0:8080/hook")

    def test_ipv6_loopback_blocked(self):
        """IPv6 ::1 is blocked."""
        with pytest.raises(SSRFError, match="blocked"):
            validate_webhook_url("http://[::1]/webhook")

    # -----------------------------------------------------------------------
    # Invalid URLs
    # -----------------------------------------------------------------------

    def test_empty_url_rejected(self):
        """Empty URL is rejected."""
        with pytest.raises(SSRFError, match="non-empty"):
            validate_webhook_url("")

    def test_none_url_rejected(self):
        """None URL is rejected."""
        with pytest.raises(SSRFError, match="non-empty"):
            validate_webhook_url(None)

    def test_ftp_scheme_rejected(self):
        """Non-HTTP schemes are rejected."""
        with pytest.raises(SSRFError, match="scheme"):
            validate_webhook_url("ftp://example.com/file")

    def test_file_scheme_rejected(self):
        """File scheme is rejected."""
        with pytest.raises(SSRFError, match="scheme"):
            validate_webhook_url("file:///etc/passwd")

    def test_no_hostname_rejected(self):
        """URL without hostname is rejected."""
        with pytest.raises(SSRFError, match="hostname"):
            validate_webhook_url("http:///path")

    # -----------------------------------------------------------------------
    # DNS resolution of hostnames to blocked IPs
    # -----------------------------------------------------------------------

    def test_hostname_resolving_to_loopback_blocked(self):
        """Hostname resolving to 127.0.0.1 is blocked."""
        fake_results = [
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ]
        with patch("mcp_network.security.ssrf.socket.getaddrinfo", return_value=fake_results):
            with pytest.raises(SSRFError, match="blocked"):
                validate_webhook_url("https://evil.example.com/webhook")

    def test_hostname_resolving_to_metadata_blocked(self):
        """Hostname resolving to 169.254.169.254 is blocked."""
        fake_results = [
            (2, 1, 6, "", ("169.254.169.254", 443)),
        ]
        with patch("mcp_network.security.ssrf.socket.getaddrinfo", return_value=fake_results):
            with pytest.raises(SSRFError, match="blocked"):
                validate_webhook_url("https://metadata.evil.com/webhook")

    def test_unresolvable_hostname_rejected(self):
        """Unresolvable hostname is rejected."""
        import socket
        with patch("mcp_network.security.ssrf.socket.getaddrinfo", side_effect=socket.gaierror):
            with pytest.raises(SSRFError, match="resolve"):
                validate_webhook_url("https://nonexistent-host-abc123.invalid/hook")

    # -----------------------------------------------------------------------
    # Valid URLs
    # -----------------------------------------------------------------------

    def test_valid_https_external_url(self):
        """Valid external HTTPS URL passes."""
        fake_results = [
            (2, 1, 6, "", ("52.12.34.56", 443)),
        ]
        with patch("mcp_network.security.ssrf.socket.getaddrinfo", return_value=fake_results):
            result = validate_webhook_url("https://hooks.slack.com/services/T00/B00/xxx")
            assert result == "https://hooks.slack.com/services/T00/B00/xxx"

    def test_valid_http_external_url(self):
        """HTTP URL to public address passes (for dev use)."""
        fake_results = [
            (2, 1, 6, "", ("93.184.216.34", 80)),
        ]
        with patch("mcp_network.security.ssrf.socket.getaddrinfo", return_value=fake_results):
            result = validate_webhook_url("http://example.com/hook")
            assert result == "http://example.com/hook"

    def test_valid_public_ip_literal(self):
        """Public IP literal passes."""
        result = validate_webhook_url("https://52.12.34.56/webhook")
        assert "52.12.34.56" in result

    def test_url_whitespace_stripped(self):
        """Leading/trailing whitespace is stripped."""
        result = validate_webhook_url("  https://52.12.34.56/webhook  ")
        assert result == "https://52.12.34.56/webhook"
