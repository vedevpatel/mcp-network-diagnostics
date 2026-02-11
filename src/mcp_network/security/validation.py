"""Input validation and sanitization."""

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


class InputValidator:
    """Validates and sanitizes user inputs."""

    # Dangerous patterns that indicate injection attempts
    INJECTION_PATTERNS = [
        r"[;&|`$]",           # Shell metacharacters
        r"\.\./",             # Path traversal
        r"<script",           # XSS (case-insensitive handled below)
        r"{{.*}}",            # Template injection (Jinja2, etc.)
        r"\$\{.*\}",          # Template injection (bash-style)
        r"\x00",              # Null bytes
        r"--",                # SQL comment
        r"/\*.*\*/",          # C-style comment
    ]

    # Valid patterns for specific field types
    DEVICE_ID_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"
    IP_PATTERN = r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
    HOSTNAME_PATTERN = r"^[a-zA-Z0-9](?:[-a-zA-Z0-9]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[-a-zA-Z0-9]{0,61}[a-zA-Z0-9])?)*$"
    INTERFACE_PATTERN = r"^[a-zA-Z0-9_/.-]{1,128}$"
    KEY_ID_PATTERN = r"^[a-zA-Z0-9_-]{1,16}$"

    def validate_device_id(self, device_id: str) -> str:
        """Validate and sanitize device ID.

        Args:
            device_id: Device identifier

        Returns:
            Sanitized device ID

        Raises:
            ValidationError: If validation fails
        """
        if not device_id or not isinstance(device_id, str):
            raise ValidationError("Device ID must be a non-empty string")

        device_id = device_id.strip()

        if not re.match(self.DEVICE_ID_PATTERN, device_id):
            raise ValidationError(
                f"Invalid device ID: '{device_id}'. "
                "Must be 1-64 characters, alphanumeric, hyphens, and underscores only"
            )

        return device_id

    def validate_destination(self, dest: str) -> str:
        """Validate destination (IP address or hostname).

        Args:
            dest: Destination to validate

        Returns:
            Sanitized destination

        Raises:
            ValidationError: If validation fails
        """
        if not dest or not isinstance(dest, str):
            raise ValidationError("Destination must be a non-empty string")

        dest = dest.strip()

        # Check if IP address
        if re.match(self.IP_PATTERN, dest):
            return dest

        # Check if hostname
        if re.match(self.HOSTNAME_PATTERN, dest):
            # Additional length check
            if len(dest) > 253:
                raise ValidationError("Hostname too long (max 253 characters)")
            return dest

        raise ValidationError(
            f"Invalid destination: '{dest}'. "
            "Must be a valid IP address or hostname"
        )

    # Schemes allowed for HTTP probing
    _ALLOWED_URL_SCHEMES = {"http", "https"}

    def _is_internal_ip(self, ip_str: str) -> bool:
        """Check if an IP address is internal/reserved (SSRF risk).

        Args:
            ip_str: IP address string

        Returns:
            True if the IP is private, loopback, link-local, or otherwise reserved
        """
        try:
            addr = ipaddress.ip_address(ip_str)
            return (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
                or addr.is_multicast
                or addr.is_unspecified
            )
        except ValueError:
            return False

    def validate_destination_safe(self, dest: str) -> str:
        """Validate destination for consumer tools with SSRF protection.

        Accepts hostnames, IPs, or http(s) URLs.  Blocks:
        - Internal / private / loopback / link-local IPs
        - Non-http(s) URL schemes (file://, gopher://, ftp://, etc.)
        - Shell metacharacters and injection patterns

        Args:
            dest: URL, hostname, or IP address

        Returns:
            Sanitized destination string

        Raises:
            ValidationError: If validation fails
        """
        if not dest or not isinstance(dest, str):
            raise ValidationError("Destination must be a non-empty string")

        dest = dest.strip()

        if len(dest) > 2048:
            raise ValidationError("Destination too long (max 2048 characters)")

        # Check for null bytes
        if "\x00" in dest:
            raise ValidationError("Destination contains null bytes")

        # Check for shell metacharacters in the raw string
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, dest, re.IGNORECASE):
                raise ValidationError("Potentially dangerous characters in destination")

        # If it looks like a URL, validate scheme
        if "://" in dest:
            parsed = urlparse(dest)
            if parsed.scheme.lower() not in self._ALLOWED_URL_SCHEMES:
                raise ValidationError(
                    f"URL scheme '{parsed.scheme}' is not allowed. "
                    "Only http and https are permitted."
                )
            # Extract host portion for IP check
            hostname = parsed.hostname or ""
        else:
            hostname = dest

        # Strip port if present on a bare host:port
        if ":" in hostname and not hostname.startswith("["):
            hostname = hostname.rsplit(":", 1)[0]

        # Validate as IP or hostname
        if re.match(self.IP_PATTERN, hostname):
            if self._is_internal_ip(hostname):
                raise ValidationError(
                    f"Destination '{hostname}' is an internal/private IP address. "
                    "Only public IP addresses are allowed."
                )
            return dest

        if re.match(self.HOSTNAME_PATTERN, hostname):
            if len(hostname) > 253:
                raise ValidationError("Hostname too long (max 253 characters)")
            # Block common internal hostnames
            lower = hostname.lower()
            if lower in ("localhost", "localhost.localdomain"):
                raise ValidationError("Destination 'localhost' is not allowed.")
            return dest

        raise ValidationError(
            f"Invalid destination: '{dest}'. "
            "Must be a valid IP address, hostname, or http(s) URL."
        )

    def validate_url_safe(self, url: str) -> str:
        """Validate a URL for safe HTTP probing (SSRF protection).

        Only http:// and https:// schemes are allowed.
        Internal/private IPs are blocked.

        Args:
            url: URL to validate

        Returns:
            Validated URL

        Raises:
            ValidationError: If URL is unsafe
        """
        if not url or not isinstance(url, str):
            raise ValidationError("URL must be a non-empty string")

        url = url.strip()

        parsed = urlparse(url)
        if parsed.scheme.lower() not in self._ALLOWED_URL_SCHEMES:
            raise ValidationError(
                f"URL scheme '{parsed.scheme}' is not allowed. "
                "Only http and https are permitted."
            )

        hostname = parsed.hostname or ""
        if re.match(self.IP_PATTERN, hostname):
            if self._is_internal_ip(hostname):
                raise ValidationError(
                    f"URL target '{hostname}' is an internal/private IP address."
                )

        lower = hostname.lower()
        if lower in ("localhost", "localhost.localdomain"):
            raise ValidationError("URL target 'localhost' is not allowed.")

        return url

    def validate_command(self, command: str) -> str:
        """Validate and sanitize command input.

        Args:
            command: Command to validate

        Returns:
            Sanitized command

        Raises:
            ValidationError: If validation fails
        """
        if not command or not isinstance(command, str):
            raise ValidationError("Command must be a non-empty string")

        command = command.strip()

        # Check for dangerous patterns
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                raise ValidationError("Potentially dangerous input detected in command")

        # Check length
        if len(command) > 1000:
            raise ValidationError("Command too long (max 1000 characters)")

        return command

    def validate_intent(self, intent: str) -> str:
        """Validate natural language intent.

        Args:
            intent: Intent text to validate

        Returns:
            Sanitized intent

        Raises:
            ValidationError: If validation fails
        """
        if not intent or not isinstance(intent, str):
            raise ValidationError("Intent must be a non-empty string")

        intent = intent.strip()

        # Max length check
        if len(intent) > 500:
            raise ValidationError("Intent too long (max 500 characters)")

        # Check for injection patterns
        for pattern in self.INJECTION_PATTERNS:
            if re.search(pattern, intent, re.IGNORECASE):
                raise ValidationError("Invalid characters in intent")

        return intent

    def validate_interface(self, interface: str) -> str:
        """Validate interface name.

        Args:
            interface: Interface name

        Returns:
            Sanitized interface name

        Raises:
            ValidationError: If validation fails
        """
        if not interface or not isinstance(interface, str):
            raise ValidationError("Interface must be a non-empty string")

        interface = interface.strip()

        if not re.match(self.INTERFACE_PATTERN, interface):
            raise ValidationError(
                f"Invalid interface: '{interface}'. "
                "Must be 1-128 characters, alphanumeric and common punctuation only"
            )

        return interface

    def validate_key_id(self, key_id: str) -> str:
        """Validate API key ID.

        Args:
            key_id: Key ID to validate

        Returns:
            Sanitized key ID

        Raises:
            ValidationError: If validation fails
        """
        if not key_id or not isinstance(key_id, str):
            raise ValidationError("Key ID must be a non-empty string")

        key_id = key_id.strip()

        if not re.match(self.KEY_ID_PATTERN, key_id):
            raise ValidationError(
                f"Invalid key ID: '{key_id}'. "
                "Must be 1-16 characters, alphanumeric, hyphens, and underscores only"
            )

        return key_id

    def validate_positive_int(self, value: Any, name: str, max_value: int = None) -> int:
        """Validate positive integer.

        Args:
            value: Value to validate
            name: Field name for error messages
            max_value: Optional maximum value

        Returns:
            Validated integer

        Raises:
            ValidationError: If validation fails
        """
        try:
            int_value = int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"{name} must be an integer")

        if int_value < 1:
            raise ValidationError(f"{name} must be positive")

        if max_value and int_value > max_value:
            raise ValidationError(f"{name} must be <= {max_value}")

        return int_value

    def validate_port(self, port: Any) -> int:
        """Validate network port number.

        Args:
            port: Port number

        Returns:
            Validated port

        Raises:
            ValidationError: If validation fails
        """
        return self.validate_positive_int(port, "Port", max_value=65535)

    def validate_role(self, role_str: str) -> str:
        """Validate role string.

        Args:
            role_str: Role name

        Returns:
            Validated role string

        Raises:
            ValidationError: If validation fails
        """
        valid_roles = ["consumer", "operator", "admin", "superuser"]

        role_str = role_str.strip().lower()

        if role_str not in valid_roles:
            raise ValidationError(
                f"Invalid role: '{role_str}'. "
                f"Must be one of: {', '.join(valid_roles)}"
            )

        return role_str

    def sanitize_output(self, text: str) -> str:
        """Sanitize text for safe display (prevent XSS in web contexts).

        Args:
            text: Text to sanitize

        Returns:
            Sanitized text
        """
        if not isinstance(text, str):
            return str(text)

        # Replace dangerous HTML characters
        replacements = {
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#x27;',
            '/': '&#x2F;',
        }

        for char, escape in replacements.items():
            text = text.replace(char, escape)

        return text
