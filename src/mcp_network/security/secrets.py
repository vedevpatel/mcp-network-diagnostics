"""Encrypted secrets storage for device credentials."""

import base64
import json
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class SecretsLockedError(Exception):
    """Raised when trying to access locked secrets."""
    pass


class SecretsManager:
    """Manages encrypted storage of sensitive credentials.

    Uses Fernet (AES-256-GCM) for symmetric encryption.
    Master password is derived using PBKDF2-HMAC-SHA256.
    """

    def __init__(self, secrets_file: Optional[str] = None):
        """Initialize secrets manager.

        Args:
            secrets_file: Path to encrypted secrets file.
                         Defaults to ~/.mcp_network/secrets.enc
        """
        if secrets_file is None:
            secrets_file = str(Path.home() / ".mcp_network" / "secrets.enc")

        self.secrets_file = Path(secrets_file)
        self.salt_file = self.secrets_file.with_suffix(".salt")

        self._fernet: Optional[Fernet] = None
        self._secrets: dict = {}
        self._locked = True

    def unlock(self, master_password: str):
        """Unlock secrets with master password.

        Args:
            master_password: Master password to decrypt secrets

        Raises:
            InvalidToken: If password is incorrect
        """
        # Get or create salt
        salt = self._get_or_create_salt()

        # Derive encryption key from password using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,  # OWASP recommendation for 2023
        )
        key = base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
        self._fernet = Fernet(key)

        # Load and decrypt secrets if file exists
        if self.secrets_file.exists():
            try:
                encrypted = self.secrets_file.read_bytes()
                decrypted = self._fernet.decrypt(encrypted)
                self._secrets = json.loads(decrypted)
            except InvalidToken:
                self._fernet = None
                raise InvalidToken("Invalid master password")
            except Exception as e:
                self._fernet = None
                raise Exception(f"Failed to load secrets: {e}")

        self._locked = False

    def lock(self):
        """Lock secrets and clear from memory."""
        self._fernet = None
        self._secrets = {}
        self._locked = True

    def is_locked(self) -> bool:
        """Check if secrets are locked.

        Returns:
            True if locked, False if unlocked
        """
        return self._locked

    def get_credential(self, device_id: str) -> Optional[dict]:
        """Get credentials for a device.

        Args:
            device_id: Device identifier

        Returns:
            Dict with username, password, key_file, or None if not found

        Raises:
            SecretsLockedError: If secrets are locked
        """
        if self._locked:
            raise SecretsLockedError("Secrets are locked. Call unlock() first.")

        return self._secrets.get(f"device:{device_id}")

    def set_credential(
        self,
        device_id: str,
        username: str,
        password: Optional[str] = None,
        key_file: Optional[str] = None,
    ):
        """Store credentials for a device.

        Args:
            device_id: Device identifier
            username: SSH username
            password: SSH password (optional if using key_file)
            key_file: Path to SSH private key (optional if using password)

        Raises:
            SecretsLockedError: If secrets are locked
            ValueError: If neither password nor key_file provided
        """
        if self._locked:
            raise SecretsLockedError("Secrets are locked. Call unlock() first.")

        if not password and not key_file:
            raise ValueError("Must provide either password or key_file")

        self._secrets[f"device:{device_id}"] = {
            "username": username,
            "password": password,
            "key_file": key_file,
        }

        self._save()

    def delete_credential(self, device_id: str) -> bool:
        """Delete credentials for a device.

        Args:
            device_id: Device identifier

        Returns:
            True if deleted, False if not found

        Raises:
            SecretsLockedError: If secrets are locked
        """
        if self._locked:
            raise SecretsLockedError("Secrets are locked. Call unlock() first.")

        key = f"device:{device_id}"
        if key in self._secrets:
            del self._secrets[key]
            self._save()
            return True
        return False

    def list_devices(self) -> list[str]:
        """List all devices with stored credentials.

        Returns:
            List of device IDs

        Raises:
            SecretsLockedError: If secrets are locked
        """
        if self._locked:
            raise SecretsLockedError("Secrets are locked. Call unlock() first.")

        devices = []
        for key in self._secrets.keys():
            if key.startswith("device:"):
                devices.append(key.split(":", 1)[1])
        return sorted(devices)

    def change_master_password(self, old_password: str, new_password: str):
        """Change the master password.

        Re-encrypts all secrets with the new password.

        Args:
            old_password: Current master password
            new_password: New master password

        Raises:
            InvalidToken: If old password is incorrect
        """
        # Verify old password
        self.unlock(old_password)

        # Save current secrets
        secrets_backup = self._secrets.copy()

        # Lock
        self.lock()

        # Remove old encrypted file and salt
        if self.secrets_file.exists():
            self.secrets_file.unlink()
        if self.salt_file.exists():
            self.salt_file.unlink()

        # Unlock with new password (creates new salt, no existing file to decrypt)
        self.unlock(new_password)

        # Restore secrets and save with new encryption
        self._secrets = secrets_backup
        self._save()

    def export_plaintext(self, output_file: str):
        """Export secrets to plaintext JSON (for backup/migration).

        WARNING: Output file contains plaintext credentials!

        Args:
            output_file: Path to output file

        Raises:
            SecretsLockedError: If secrets are locked
        """
        if self._locked:
            raise SecretsLockedError("Secrets are locked. Call unlock() first.")

        output_path = Path(output_file)
        output_path.write_text(json.dumps(self._secrets, indent=2))

        # Set restrictive permissions
        try:
            os.chmod(output_path, 0o600)
        except Exception:
            pass  # Windows or permission error

    def import_plaintext(self, input_file: str):
        """Import secrets from plaintext JSON.

        Args:
            input_file: Path to input file

        Raises:
            SecretsLockedError: If secrets are locked
        """
        if self._locked:
            raise SecretsLockedError("Secrets are locked. Call unlock() first.")

        input_path = Path(input_file)
        self._secrets = json.loads(input_path.read_text())
        self._save()

    def _save(self):
        """Encrypt and save secrets to disk."""
        if not self._fernet:
            raise SecretsLockedError("Cannot save while locked")

        # Ensure directory exists
        self.secrets_file.parent.mkdir(parents=True, exist_ok=True)

        # Encrypt secrets
        plaintext = json.dumps(self._secrets, indent=2).encode()
        encrypted = self._fernet.encrypt(plaintext)

        # Write atomically
        temp_file = self.secrets_file.with_suffix(".tmp")
        temp_file.write_bytes(encrypted)
        temp_file.replace(self.secrets_file)

        # Set restrictive permissions (Unix only)
        try:
            os.chmod(self.secrets_file, 0o600)
        except Exception:
            pass  # Windows or permission error

    def _get_or_create_salt(self) -> bytes:
        """Get existing salt or create new one.

        Returns:
            16-byte salt
        """
        if self.salt_file.exists():
            return self.salt_file.read_bytes()

        # Create new salt
        salt = os.urandom(16)

        # Ensure directory exists
        self.salt_file.parent.mkdir(parents=True, exist_ok=True)

        # Save salt
        self.salt_file.write_bytes(salt)

        # Set restrictive permissions
        try:
            os.chmod(self.salt_file, 0o600)
        except Exception:
            pass

        return salt
