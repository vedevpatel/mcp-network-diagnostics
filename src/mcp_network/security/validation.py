"""Input validation and sanitization."""

import re
from typing import Any


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
