"""Authentication system with API key management."""

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Optional


class Role(Enum):
    """User roles with hierarchical permissions."""
    CONSUMER = "consumer"      # Edge tools only
    OPERATOR = "operator"      # + Device access (read-only)
    ADMIN = "admin"            # + Agent control, intents
    SUPERUSER = "superuser"    # + Write commands, credential mgmt

    def __lt__(self, other):
        """Enable role comparison for hierarchy checking."""
        if not isinstance(other, Role):
            return NotImplemented
        order = [Role.CONSUMER, Role.OPERATOR, Role.ADMIN, Role.SUPERUSER]
        return order.index(self) < order.index(other)

    def __le__(self, other):
        return self == other or self < other


@dataclass
class APIKey:
    """API key with metadata."""
    key_id: str                           # Public identifier (8 chars)
    key_hash: str                         # SHA-256 of secret (never store plaintext)
    role: Role
    created_at: float
    expires_at: Optional[float] = None    # Unix timestamp or None
    rate_limit: int = 60                  # Requests per minute
    allowed_tools: Optional[list[str]] = None   # None = all tools for role
    allowed_devices: Optional[list[str]] = None # None = all devices
    description: str = ""
    enabled: bool = True


class AuthManager:
    """Manages API key lifecycle and authentication."""

    def __init__(self, keys_file: Optional[str] = None):
        """Initialize auth manager.

        Args:
            keys_file: Path to API keys JSON file. Defaults to ~/.mcp_network/api_keys.json
        """
        if keys_file is None:
            keys_file = str(Path.home() / ".mcp_network" / "api_keys.json")

        self.keys_file = Path(keys_file)
        self.keys: dict[str, APIKey] = {}
        self._load_keys()

    def generate_key(
        self,
        role: Role,
        description: str,
        expires_days: Optional[int] = None,
        rate_limit: Optional[int] = None,
        allowed_tools: Optional[list[str]] = None,
        allowed_devices: Optional[list[str]] = None,
    ) -> tuple[str, APIKey]:
        """Generate a new API key.

        Args:
            role: User role for this key
            description: Human-readable description
            expires_days: Days until expiration (None = never)
            rate_limit: Custom rate limit (None = use default)
            allowed_tools: Subset of tools (None = all for role)
            allowed_devices: Subset of devices (None = all)

        Returns:
            (plaintext_key, key_object) - plaintext shown ONCE, never stored
        """
        # Generate random components
        plaintext = secrets.token_urlsafe(32)
        key_id = secrets.token_urlsafe(8)
        key_hash = hashlib.sha256(plaintext.encode()).hexdigest()

        # Calculate expiration
        expires_at = None
        if expires_days is not None:
            expires_at = time.time() + (expires_days * 86400)

        # Determine rate limit
        if rate_limit is None:
            rate_limit = self._default_rate_limit(role)

        # Create key object
        api_key = APIKey(
            key_id=key_id,
            key_hash=key_hash,
            role=role,
            created_at=time.time(),
            expires_at=expires_at,
            rate_limit=rate_limit,
            allowed_tools=allowed_tools,
            allowed_devices=allowed_devices,
            description=description,
            enabled=True,
        )

        # Store key
        self.keys[key_id] = api_key
        self._save_keys()

        # Return plaintext ONCE
        full_key = f"mcp_{key_id}_{plaintext}"
        return full_key, api_key

    def authenticate(self, provided_key: str) -> Optional[APIKey]:
        """Authenticate an API key.

        Args:
            provided_key: Full key string (mcp_<key_id>_<secret>)

        Returns:
            APIKey object if valid, None otherwise
        """
        # Validate format
        if not provided_key.startswith("mcp_"):
            return None

        parts = provided_key.split("_", 2)
        if len(parts) != 3:
            return None

        _, key_id, secret = parts

        # Find key
        if key_id not in self.keys:
            return None

        api_key = self.keys[key_id]

        # Check if enabled
        if not api_key.enabled:
            return None

        # Check expiration
        if api_key.expires_at and time.time() > api_key.expires_at:
            return None

        # Verify hash (constant-time comparison)
        provided_hash = hashlib.sha256(secret.encode()).hexdigest()
        if not secrets.compare_digest(provided_hash, api_key.key_hash):
            return None

        return api_key

    def revoke_key(self, key_id: str) -> bool:
        """Revoke an API key (disable it).

        Args:
            key_id: Key ID to revoke

        Returns:
            True if revoked, False if not found
        """
        if key_id not in self.keys:
            return False

        self.keys[key_id].enabled = False
        self._save_keys()
        return True

    def delete_key(self, key_id: str) -> bool:
        """Permanently delete an API key.

        Args:
            key_id: Key ID to delete

        Returns:
            True if deleted, False if not found
        """
        if key_id not in self.keys:
            return False

        del self.keys[key_id]
        self._save_keys()
        return True

    def list_keys(self, include_disabled: bool = False) -> list[APIKey]:
        """List all API keys (without secrets).

        Args:
            include_disabled: Include disabled/revoked keys

        Returns:
            List of APIKey objects
        """
        keys = list(self.keys.values())
        if not include_disabled:
            keys = [k for k in keys if k.enabled]
        return keys

    def get_key(self, key_id: str) -> Optional[APIKey]:
        """Get a specific API key by ID.

        Args:
            key_id: Key ID to retrieve

        Returns:
            APIKey object or None
        """
        return self.keys.get(key_id)

    def _default_rate_limit(self, role: Role) -> int:
        """Get default rate limit for a role.

        Args:
            role: User role

        Returns:
            Requests per minute
        """
        return {
            Role.CONSUMER: 60,    # 1/sec
            Role.OPERATOR: 120,   # 2/sec
            Role.ADMIN: 300,      # 5/sec
            Role.SUPERUSER: 600,  # 10/sec
        }[role]

    def _load_keys(self):
        """Load API keys from disk."""
        if not self.keys_file.exists():
            return

        try:
            with open(self.keys_file) as f:
                data = json.load(f)

            for key_id, key_data in data.items():
                # Deserialize role enum
                key_data["role"] = Role(key_data["role"])

                # Handle optional fields
                if key_data.get("allowed_tools") == []:
                    key_data["allowed_tools"] = None
                if key_data.get("allowed_devices") == []:
                    key_data["allowed_devices"] = None

                self.keys[key_id] = APIKey(**key_data)

        except Exception as e:
            # Log error but don't crash
            print(f"Warning: Failed to load API keys: {e}")

    def _save_keys(self):
        """Save API keys to disk."""
        # Ensure directory exists
        self.keys_file.parent.mkdir(parents=True, exist_ok=True)

        # Serialize keys
        data = {}
        for key_id, api_key in self.keys.items():
            key_dict = asdict(api_key)
            # Serialize role enum
            key_dict["role"] = api_key.role.value
            # Serialize None as empty list for JSON
            if key_dict["allowed_tools"] is None:
                key_dict["allowed_tools"] = []
            if key_dict["allowed_devices"] is None:
                key_dict["allowed_devices"] = []
            data[key_id] = key_dict

        # Write atomically
        temp_file = self.keys_file.with_suffix(".tmp")
        with open(temp_file, "w") as f:
            json.dump(data, f, indent=2)

        temp_file.replace(self.keys_file)

        # Set restrictive permissions (Unix only)
        try:
            import os
            os.chmod(self.keys_file, 0o600)
        except Exception:
            pass  # Windows or permission error
