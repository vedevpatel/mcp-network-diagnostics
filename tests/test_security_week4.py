"""Tests for Week 4 security: secrets management and TLS."""

import pytest
from pathlib import Path
from cryptography.fernet import InvalidToken

from mcp_network.security import (
    SecretsManager,
    SecretsLockedError,
    TLSConfig,
    ServerConfig,
    generate_self_signed_cert,
)


# ============================================================================
# Secrets Management Tests
# ============================================================================

class TestSecretsManager:
    """Tests for encrypted secrets storage."""

    def test_unlock_with_correct_password(self, tmp_path):
        """Test unlocking with correct password."""
        mgr = SecretsManager(str(tmp_path / "secrets.enc"))
        mgr.unlock("test_password")

        assert not mgr.is_locked()

    def test_cannot_access_while_locked(self, tmp_path):
        """Test that secrets cannot be accessed while locked."""
        mgr = SecretsManager(str(tmp_path / "secrets.enc"))

        with pytest.raises(SecretsLockedError):
            mgr.get_credential("device1")

    def test_store_and_retrieve_credential(self, tmp_path):
        """Test storing and retrieving credentials."""
        mgr = SecretsManager(str(tmp_path / "secrets.enc"))
        mgr.unlock("test_password")

        mgr.set_credential("router1", "admin", password="secret123")

        cred = mgr.get_credential("router1")
        assert cred["username"] == "admin"
        assert cred["password"] == "secret123"

    def test_credentials_persist_across_instances(self, tmp_path):
        """Test that credentials persist when locked/unlocked."""
        secrets_file = tmp_path / "secrets.enc"

        # Store credential
        mgr1 = SecretsManager(str(secrets_file))
        mgr1.unlock("test_password")
        mgr1.set_credential("router1", "admin", password="secret123")
        mgr1.lock()

        # Retrieve with new instance
        mgr2 = SecretsManager(str(secrets_file))
        mgr2.unlock("test_password")
        cred = mgr2.get_credential("router1")

        assert cred["username"] == "admin"
        assert cred["password"] == "secret123"

    def test_wrong_password_raises_error(self, tmp_path):
        """Test that wrong password raises InvalidToken."""
        secrets_file = tmp_path / "secrets.enc"

        # Create with one password
        mgr1 = SecretsManager(str(secrets_file))
        mgr1.unlock("correct_password")
        mgr1.set_credential("router1", "admin", password="secret")
        mgr1.lock()

        # Try with wrong password
        mgr2 = SecretsManager(str(secrets_file))
        with pytest.raises(InvalidToken):
            mgr2.unlock("wrong_password")

    def test_secrets_encrypted_at_rest(self, tmp_path):
        """Test that secrets are encrypted on disk."""
        secrets_file = tmp_path / "secrets.enc"

        mgr = SecretsManager(str(secrets_file))
        mgr.unlock("test_password")
        mgr.set_credential("router1", "admin", password="secret123")
        mgr.lock()

        # Read raw file
        content = secrets_file.read_bytes()

        # Should not contain plaintext
        assert b"admin" not in content
        assert b"secret123" not in content
        assert b"router1" not in content

    def test_delete_credential(self, tmp_path):
        """Test deleting credentials."""
        mgr = SecretsManager(str(tmp_path / "secrets.enc"))
        mgr.unlock("test_password")

        mgr.set_credential("router1", "admin", password="secret")
        assert mgr.delete_credential("router1")
        assert mgr.get_credential("router1") is None

    def test_delete_nonexistent_credential(self, tmp_path):
        """Test deleting non-existent credential returns False."""
        mgr = SecretsManager(str(tmp_path / "secrets.enc"))
        mgr.unlock("test_password")

        assert not mgr.delete_credential("nonexistent")

    def test_list_devices(self, tmp_path):
        """Test listing devices with credentials."""
        mgr = SecretsManager(str(tmp_path / "secrets.enc"))
        mgr.unlock("test_password")

        mgr.set_credential("router1", "admin", password="secret1")
        mgr.set_credential("router2", "admin", password="secret2")
        mgr.set_credential("switch1", "admin", password="secret3")

        devices = mgr.list_devices()
        assert devices == ["router1", "router2", "switch1"]

    def test_credential_with_key_file(self, tmp_path):
        """Test storing credential with SSH key file."""
        mgr = SecretsManager(str(tmp_path / "secrets.enc"))
        mgr.unlock("test_password")

        mgr.set_credential(
            "router1",
            "admin",
            key_file="/path/to/key.pem",
        )

        cred = mgr.get_credential("router1")
        assert cred["username"] == "admin"
        assert cred["key_file"] == "/path/to/key.pem"
        assert cred["password"] is None

    def test_requires_password_or_key_file(self, tmp_path):
        """Test that either password or key_file is required."""
        mgr = SecretsManager(str(tmp_path / "secrets.enc"))
        mgr.unlock("test_password")

        with pytest.raises(ValueError):
            mgr.set_credential("router1", "admin")

    def test_change_master_password(self, tmp_path):
        """Test changing master password."""
        secrets_file = tmp_path / "secrets.enc"

        # Create with old password
        mgr1 = SecretsManager(str(secrets_file))
        mgr1.unlock("old_password")
        mgr1.set_credential("router1", "admin", password="secret")
        mgr1.lock()

        # Change password
        mgr2 = SecretsManager(str(secrets_file))
        mgr2.change_master_password("old_password", "new_password")

        # Verify old password doesn't work
        mgr3 = SecretsManager(str(secrets_file))
        with pytest.raises(InvalidToken):
            mgr3.unlock("old_password")

        # Verify new password works and data is intact
        mgr4 = SecretsManager(str(secrets_file))
        mgr4.unlock("new_password")
        cred = mgr4.get_credential("router1")
        assert cred["password"] == "secret"

    def test_export_plaintext(self, tmp_path):
        """Test exporting secrets to plaintext."""
        mgr = SecretsManager(str(tmp_path / "secrets.enc"))
        mgr.unlock("test_password")
        mgr.set_credential("router1", "admin", password="secret")

        export_file = tmp_path / "export.json"
        mgr.export_plaintext(str(export_file))

        # Check file exists and contains plaintext
        assert export_file.exists()
        content = export_file.read_text()
        assert "admin" in content
        assert "secret" in content

    def test_import_plaintext(self, tmp_path):
        """Test importing secrets from plaintext."""
        import json

        # Create plaintext export
        export_data = {
            "device:router1": {
                "username": "admin",
                "password": "secret123",
                "key_file": None,
            }
        }
        export_file = tmp_path / "import.json"
        export_file.write_text(json.dumps(export_data))

        # Import
        mgr = SecretsManager(str(tmp_path / "secrets.enc"))
        mgr.unlock("test_password")
        mgr.import_plaintext(str(export_file))

        # Verify
        cred = mgr.get_credential("router1")
        assert cred["username"] == "admin"
        assert cred["password"] == "secret123"

    def test_lock_clears_memory(self, tmp_path):
        """Test that lock() clears secrets from memory."""
        mgr = SecretsManager(str(tmp_path / "secrets.enc"))
        mgr.unlock("test_password")
        mgr.set_credential("router1", "admin", password="secret")

        mgr.lock()

        assert mgr.is_locked()
        assert mgr._secrets == {}
        assert mgr._fernet is None


# ============================================================================
# TLS Configuration Tests
# ============================================================================

class TestTLSConfig:
    """Tests for TLS configuration."""

    def test_default_config(self):
        """Test default TLS configuration."""
        tls = TLSConfig()

        assert not tls.enabled
        assert tls.min_version == "TLSv1.3"
        assert not tls.verify_client

    def test_enabled_config(self):
        """Test enabled TLS configuration."""
        tls = TLSConfig(
            enabled=True,
            cert_file="/path/to/cert.pem",
            key_file="/path/to/key.pem",
        )

        assert tls.enabled
        assert tls.cert_file == "/path/to/cert.pem"
        assert tls.key_file == "/path/to/key.pem"

    def test_mtls_config(self):
        """Test mutual TLS configuration."""
        tls = TLSConfig(
            enabled=True,
            cert_file="/path/to/cert.pem",
            key_file="/path/to/key.pem",
            verify_client=True,
            client_ca_file="/path/to/ca.pem",
        )

        assert tls.verify_client
        assert tls.client_ca_file == "/path/to/ca.pem"


class TestServerConfig:
    """Tests for server configuration."""

    def test_default_config(self):
        """Test default server configuration."""
        config = ServerConfig()

        assert config.host == "127.0.0.1"
        assert config.port == 8080
        assert config.require_auth
        assert not config.tls.enabled

    def test_secure_public_preset(self):
        """Test secure public preset."""
        config = ServerConfig.secure_public()

        assert config.host == "0.0.0.0"
        assert config.port == 443
        assert config.tls.enabled
        assert config.require_auth
        assert not config.allow_anonymous_consumer

    def test_local_development_preset(self):
        """Test local development preset."""
        config = ServerConfig.local_development()

        assert config.host == "127.0.0.1"
        assert not config.tls.enabled
        assert not config.require_auth
        assert not config.enable_rate_limiting

    def test_secure_internal_preset(self):
        """Test secure internal preset."""
        config = ServerConfig.secure_internal()

        assert config.host == "0.0.0.0"
        assert config.tls.enabled
        assert config.require_auth
        assert config.allow_anonymous_consumer

    def test_to_dict(self):
        """Test converting config to dictionary."""
        config = ServerConfig(host="0.0.0.0", port=443)
        data = config.to_dict()

        assert data["host"] == "0.0.0.0"
        assert data["port"] == 443
        assert "tls" in data

    def test_from_dict(self):
        """Test creating config from dictionary."""
        data = {
            "host": "0.0.0.0",
            "port": 443,
            "require_auth": True,
            "tls": {
                "enabled": True,
                "min_version": "TLSv1.3",
            }
        }

        config = ServerConfig.from_dict(data.copy())

        assert config.host == "0.0.0.0"
        assert config.port == 443
        assert config.tls.enabled

    def test_to_file_and_from_file(self, tmp_path):
        """Test saving and loading config file."""
        config_file = tmp_path / "config.yaml"

        # Save
        config1 = ServerConfig(host="0.0.0.0", port=443)
        config1.to_file(str(config_file))

        # Load
        config2 = ServerConfig.from_file(str(config_file))

        assert config2.host == "0.0.0.0"
        assert config2.port == 443

    def test_validate_valid_config(self):
        """Test validation of valid configuration."""
        config = ServerConfig.secure_public()
        config.tls.cert_file = "/etc/ssl/cert.pem"  # Doesn't need to exist for this test
        config.tls.key_file = "/etc/ssl/key.pem"

        # Will have warnings about missing files, but structure is valid
        errors = config.validate()
        # Check that structure errors are not present (file missing is ok for test)
        assert not any("port" in e.lower() for e in errors)

    def test_validate_invalid_port(self):
        """Test validation catches invalid port."""
        config = ServerConfig(port=70000)

        errors = config.validate()
        assert any("port" in e.lower() for e in errors)

    def test_validate_tls_enabled_without_cert(self):
        """Test validation catches TLS enabled without certificate."""
        config = ServerConfig()
        config.tls.enabled = True

        errors = config.validate()
        assert any("cert_file" in e for e in errors)

    def test_is_secure(self):
        """Test security check."""
        # Secure config
        secure = ServerConfig.secure_public()
        secure.tls.cert_file = "/path/to/cert.pem"
        secure.tls.key_file = "/path/to/key.pem"
        assert secure.is_secure()

        # Insecure: public without TLS
        insecure = ServerConfig(host="0.0.0.0")
        insecure.tls.enabled = False
        assert not insecure.is_secure()

        # Insecure: no rate limiting
        insecure2 = ServerConfig()
        insecure2.enable_rate_limiting = False
        assert not insecure2.is_secure()


class TestCertificateGeneration:
    """Tests for certificate generation."""

    def test_generate_self_signed_cert(self, tmp_path):
        """Test generating self-signed certificate."""
        cert_file, key_file = generate_self_signed_cert(
            str(tmp_path),
            hostname="test.local",
            days=30,
        )

        # Check files exist
        assert Path(cert_file).exists()
        assert Path(key_file).exists()

        # Check files are PEM format
        cert_content = Path(cert_file).read_text()
        key_content = Path(key_file).read_text()

        assert "BEGIN CERTIFICATE" in cert_content
        assert "BEGIN PRIVATE KEY" in key_content or "BEGIN RSA PRIVATE KEY" in key_content
