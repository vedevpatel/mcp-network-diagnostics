"""Security configuration management."""

import yaml
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .tls import TLSConfig


@dataclass
class ServerConfig:
    """Server security configuration."""

    # Network
    host: str = "127.0.0.1"  # Default: local only
    port: int = 8080

    # TLS
    tls: TLSConfig = None

    # Authentication
    require_auth: bool = True
    allow_anonymous_consumer: bool = False  # Allow unauthenticated consumer mode tools

    # Rate limiting
    global_rate_limit: int = 1000  # Requests per minute (total)
    enable_rate_limiting: bool = True

    # Timeouts
    request_timeout_seconds: int = 30
    idle_timeout_seconds: int = 300

    # Audit logging
    enable_audit_logging: bool = True
    audit_log_dir: Optional[str] = None  # Defaults to ~/.mcp_network/audit

    # Secrets
    secrets_file: Optional[str] = None  # Defaults to ~/.mcp_network/secrets.enc

    # API Keys
    api_keys_file: Optional[str] = None  # Defaults to ~/.mcp_network/api_keys.json

    def __post_init__(self):
        """Initialize TLS config if not provided."""
        if self.tls is None:
            self.tls = TLSConfig()

    @classmethod
    def from_file(cls, path: str) -> "ServerConfig":
        """Load configuration from YAML file.

        Args:
            path: Path to YAML configuration file

        Returns:
            ServerConfig instance

        Raises:
            FileNotFoundError: If file doesn't exist
            yaml.YAMLError: If file is invalid YAML
        """
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(config_path) as f:
            data = yaml.safe_load(f)

        # Handle TLS config separately
        tls_data = data.pop("tls", {})
        tls_config = TLSConfig(**tls_data) if tls_data else TLSConfig()

        return cls(tls=tls_config, **data)

    @classmethod
    def from_dict(cls, data: dict) -> "ServerConfig":
        """Load configuration from dictionary.

        Args:
            data: Configuration dictionary

        Returns:
            ServerConfig instance
        """
        # Handle TLS config separately
        tls_data = data.pop("tls", {})
        tls_config = TLSConfig(**tls_data) if tls_data else TLSConfig()

        return cls(tls=tls_config, **data)

    def to_file(self, path: str):
        """Save configuration to YAML file.

        Args:
            path: Path to output file
        """
        config_path = Path(path)
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to dict
        data = self.to_dict()

        with open(config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def to_dict(self) -> dict:
        """Convert to dictionary.

        Returns:
            Configuration as dictionary
        """
        data = asdict(self)
        # Convert TLSConfig dataclass to dict
        if isinstance(data["tls"], TLSConfig):
            data["tls"] = asdict(data["tls"])
        return data

    @classmethod
    def secure_public(cls) -> "ServerConfig":
        """Preset for public-facing production deployment.

        Returns:
            Secure production configuration
        """
        return cls(
            host="0.0.0.0",  # Listen on all interfaces
            port=443,
            tls=TLSConfig(
                enabled=True,
                min_version="TLSv1.3",
            ),
            require_auth=True,
            allow_anonymous_consumer=False,
            global_rate_limit=1000,
            enable_rate_limiting=True,
            request_timeout_seconds=30,
            idle_timeout_seconds=300,
            enable_audit_logging=True,
        )

    @classmethod
    def local_development(cls) -> "ServerConfig":
        """Preset for local development (less secure).

        Returns:
            Development configuration
        """
        return cls(
            host="127.0.0.1",
            port=8080,
            tls=TLSConfig(enabled=False),
            require_auth=False,
            allow_anonymous_consumer=True,
            enable_rate_limiting=False,
            request_timeout_seconds=60,
            enable_audit_logging=False,
        )

    @classmethod
    def secure_internal(cls) -> "ServerConfig":
        """Preset for internal/private network deployment.

        Returns:
            Internal network configuration
        """
        return cls(
            host="0.0.0.0",
            port=8443,
            tls=TLSConfig(
                enabled=True,
                min_version="TLSv1.2",  # Slightly relaxed for older clients
            ),
            require_auth=True,
            allow_anonymous_consumer=True,  # Allow consumer tools without auth
            global_rate_limit=5000,  # Higher limit for internal use
            enable_rate_limiting=True,
            request_timeout_seconds=60,
            enable_audit_logging=True,
        )

    def validate(self) -> list[str]:
        """Validate configuration.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        # Port validation
        if not (1 <= self.port <= 65535):
            errors.append(f"Invalid port: {self.port} (must be 1-65535)")

        # TLS validation
        if self.tls.enabled:
            if not self.tls.cert_file:
                errors.append("TLS enabled but cert_file not specified")
            if not self.tls.key_file:
                errors.append("TLS enabled but key_file not specified")

            if self.tls.cert_file:
                cert_path = Path(self.tls.cert_file)
                if not cert_path.exists():
                    errors.append(f"Certificate file not found: {self.tls.cert_file}")

            if self.tls.key_file:
                key_path = Path(self.tls.key_file)
                if not key_path.exists():
                    errors.append(f"Key file not found: {self.tls.key_file}")

        # mTLS validation
        if self.tls.verify_client:
            if not self.tls.client_ca_file:
                errors.append("mTLS enabled but client_ca_file not specified")
            elif not Path(self.tls.client_ca_file).exists():
                errors.append(f"Client CA file not found: {self.tls.client_ca_file}")

        # Security warnings
        if self.host == "0.0.0.0" and not self.require_auth:
            errors.append("WARNING: Listening on all interfaces without authentication")

        if self.host == "0.0.0.0" and not self.tls.enabled:
            errors.append("WARNING: Listening on all interfaces without TLS")

        if self.global_rate_limit > 10000:
            errors.append("WARNING: Very high rate limit may enable abuse")

        return errors

    def is_secure(self) -> bool:
        """Check if configuration meets minimum security requirements.

        Returns:
            True if secure, False otherwise
        """
        if self.host == "0.0.0.0":
            # Public-facing: require auth and TLS
            if not self.require_auth or not self.tls.enabled:
                return False

        if not self.enable_rate_limiting:
            return False

        if not self.enable_audit_logging:
            return False

        return True
