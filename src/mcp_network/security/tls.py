"""TLS certificate management and configuration."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class TLSConfig:
    """TLS configuration."""
    enabled: bool = False
    cert_file: Optional[str] = None
    key_file: Optional[str] = None
    min_version: str = "TLSv1.3"
    verify_client: bool = False  # mTLS
    client_ca_file: Optional[str] = None


def generate_self_signed_cert(
    output_dir: str,
    hostname: str = "localhost",
    days: int = 365,
) -> tuple[str, str]:
    """Generate self-signed certificate for development.

    Args:
        output_dir: Directory to store certificate and key
        hostname: Hostname for certificate (default: localhost)
        days: Validity period in days (default: 365)

    Returns:
        (cert_file_path, key_file_path)

    Raises:
        subprocess.CalledProcessError: If openssl command fails
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    cert_file = output / "server.crt"
    key_file = output / "server.key"

    # Generate RSA private key and self-signed certificate
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:4096",
        "-keyout", str(key_file),
        "-out", str(cert_file),
        "-days", str(days),
        "-nodes",  # No passphrase
        "-subj", f"/CN={hostname}",
    ], check=True, capture_output=True)

    # Set restrictive permissions
    import os
    try:
        os.chmod(cert_file, 0o644)  # Cert is public
        os.chmod(key_file, 0o600)   # Key is private
    except Exception:
        pass  # Windows or permission error

    print("✓ Generated self-signed certificate:")
    print(f"  Certificate: {cert_file}")
    print(f"  Private Key: {key_file}")
    print(f"  Hostname: {hostname}")
    print(f"  Valid for: {days} days")

    return str(cert_file), str(key_file)


def generate_lets_encrypt_cert(
    domain: str,
    email: str,
    webroot: Optional[str] = None,
) -> tuple[str, str]:
    """Generate Let's Encrypt certificate for production.

    Requires certbot to be installed.

    Args:
        domain: Domain name for certificate
        email: Email for Let's Encrypt registration
        webroot: Webroot path for HTTP-01 challenge (optional, uses standalone if None)

    Returns:
        (cert_file_path, key_file_path)

    Raises:
        subprocess.CalledProcessError: If certbot command fails
        FileNotFoundError: If certbot is not installed
    """
    # Check if certbot is installed
    try:
        subprocess.run(
            ["certbot", "--version"],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError:
        raise FileNotFoundError(
            "certbot not installed. Install with:\n"
            "  macOS: brew install certbot\n"
            "  Ubuntu: apt install certbot\n"
            "  RHEL: yum install certbot"
        )

    # Determine challenge method
    if webroot:
        # HTTP-01 challenge with webroot
        cmd = [
            "certbot", "certonly", "--webroot",
            "-w", webroot,
            "-d", domain,
            "--email", email,
            "--agree-tos", "--non-interactive",
        ]
    else:
        # Standalone mode (requires port 80)
        cmd = [
            "certbot", "certonly", "--standalone",
            "-d", domain,
            "--email", email,
            "--agree-tos", "--non-interactive",
        ]

    print(f"Requesting Let's Encrypt certificate for {domain}...")
    subprocess.run(cmd, check=True)

    # Certificate paths
    cert_file = f"/etc/letsencrypt/live/{domain}/fullchain.pem"
    key_file = f"/etc/letsencrypt/live/{domain}/privkey.pem"

    print("✓ Let's Encrypt certificate obtained:")
    print(f"  Certificate: {cert_file}")
    print(f"  Private Key: {key_file}")
    print("  Renewal: Auto-renews via cron (run 'certbot renew')")

    return cert_file, key_file


def verify_cert(cert_file: str, key_file: str) -> bool:
    """Verify certificate and key match.

    Args:
        cert_file: Path to certificate file
        key_file: Path to private key file

    Returns:
        True if certificate and key match

    Raises:
        subprocess.CalledProcessError: If openssl command fails
    """
    # Get certificate modulus
    cert_modulus = subprocess.run(
        ["openssl", "x509", "-noout", "-modulus", "-in", cert_file],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # Get key modulus
    key_modulus = subprocess.run(
        ["openssl", "rsa", "-noout", "-modulus", "-in", key_file],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    return cert_modulus == key_modulus


def get_cert_info(cert_file: str) -> dict:
    """Get certificate information.

    Args:
        cert_file: Path to certificate file

    Returns:
        Dict with subject, issuer, not_before, not_after, serial

    Raises:
        subprocess.CalledProcessError: If openssl command fails
    """
    output = subprocess.run(
        ["openssl", "x509", "-noout", "-text", "-in", cert_file],
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    info = {}

    # Parse output
    for line in output.split("\n"):
        line = line.strip()
        if line.startswith("Subject:"):
            info["subject"] = line.split("Subject:", 1)[1].strip()
        elif line.startswith("Issuer:"):
            info["issuer"] = line.split("Issuer:", 1)[1].strip()
        elif line.startswith("Not Before:"):
            info["not_before"] = line.split("Not Before:", 1)[1].strip()
        elif line.startswith("Not After :"):
            info["not_after"] = line.split("Not After :", 1)[1].strip()
        elif line.startswith("Serial Number:"):
            info["serial"] = line.split("Serial Number:", 1)[1].strip()

    return info


def check_cert_expiry(cert_file: str) -> int:
    """Check days until certificate expires.

    Args:
        cert_file: Path to certificate file

    Returns:
        Number of days until expiration (negative if expired)

    Raises:
        subprocess.CalledProcessError: If openssl command fails
    """
    _output = subprocess.run(
        ["openssl", "x509", "-noout", "-checkend", "0", "-in", cert_file],
        capture_output=True,
        text=True,
    )

    # Get end date
    end_date_output = subprocess.run(
        ["openssl", "x509", "-noout", "-enddate", "-in", cert_file],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # Parse: "notAfter=Jan  1 00:00:00 2025 GMT"
    from datetime import datetime
    date_str = end_date_output.split("=", 1)[1]
    end_date = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z")
    now = datetime.utcnow()

    days_remaining = (end_date - now).days

    return days_remaining


def generate_csr(
    output_dir: str,
    domain: str,
    country: str = "US",
    state: str = "California",
    city: str = "San Francisco",
    org: str = "MCP Network Diagnostics",
) -> tuple[str, str]:
    """Generate Certificate Signing Request for commercial CA.

    Args:
        output_dir: Directory to store CSR and key
        domain: Domain name
        country: 2-letter country code
        state: State or province
        city: City
        org: Organization name

    Returns:
        (csr_file_path, key_file_path)

    Raises:
        subprocess.CalledProcessError: If openssl command fails
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    csr_file = output / f"{domain}.csr"
    key_file = output / f"{domain}.key"

    # Generate private key
    subprocess.run([
        "openssl", "genrsa", "-out", str(key_file), "4096"
    ], check=True, capture_output=True)

    # Generate CSR
    subprocess.run([
        "openssl", "req", "-new",
        "-key", str(key_file),
        "-out", str(csr_file),
        "-subj", f"/C={country}/ST={state}/L={city}/O={org}/CN={domain}",
    ], check=True, capture_output=True)

    # Set restrictive permissions
    import os
    try:
        os.chmod(key_file, 0o600)
    except Exception:
        pass

    print("✓ Generated CSR:")
    print(f"  CSR: {csr_file}")
    print(f"  Private Key: {key_file}")
    print("  Submit CSR to your Certificate Authority")

    return str(csr_file), str(key_file)
