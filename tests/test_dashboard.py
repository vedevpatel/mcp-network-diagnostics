"""Tests for web dashboard."""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from mcp_network.dashboard.app import create_app
from mcp_network.storage.database import Database
from mcp_network.storage.repositories import (
    DeviceRepository,
    IncidentRepository,
)
from mcp_network.storage.models import Device, Incident


@pytest.fixture
def test_db(tmp_path):
    """Create test database."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()


@pytest.fixture
def client(test_db, monkeypatch):
    """Create test client with mocked database and tenant=default for test data."""
    from mcp_network.storage.tenant import set_tenant_id

    def mock_get_database():
        return test_db

    # Overview does not use get_database (it uses check_my_connection). Patch only routes that do.
    monkeypatch.setattr(
        "mcp_network.dashboard.routes.devices.get_database",
        mock_get_database
    )
    monkeypatch.setattr(
        "mcp_network.dashboard.routes.incidents.get_database",
        mock_get_database
    )
    monkeypatch.setattr(
        "mcp_network.dashboard.routes.intents.get_database",
        mock_get_database
    )
    # Use tenant "default" so repo queries see test data (saved with tenant_id="default")
    original_set_tenant = set_tenant_id
    def _set_default_tenant(identity):
        original_set_tenant("default")
    monkeypatch.setattr(
        "mcp_network.dashboard.app.set_tenant_id",
        _set_default_tenant,
    )

    app = create_app()
    return TestClient(app)


@pytest.fixture
def sample_devices(test_db):
    """Create sample devices."""
    repo = DeviceRepository(test_db)
    devices = [
        Device(
            id="R1",
            name="Router-1",
            device_type="router",
            collector_type="simulated",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            metadata={"location": "DC1"},
        ),
        Device(
            id="R2",
            name="Router-2",
            device_type="router",
            collector_type="simulated",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            metadata={"location": "DC2"},
        ),
    ]
    for device in devices:
        repo.save(device)
    return devices


@pytest.fixture
def sample_incidents(test_db):
    """Create sample incidents."""
    repo = IncidentRepository(test_db)
    incidents = [
        Incident(
            id="INC-001",
            created_at=datetime.now(timezone.utc),
            severity="critical",
            summary="High CPU on R1",
            affected_devices=["R1"],
        ),
        Incident(
            id="INC-002",
            created_at=datetime.now(timezone.utc),
            severity="warning",
            summary="Interface errors on R2",
            affected_devices=["R2"],
            resolved_at=datetime.now(timezone.utc),
        ),
    ]
    for incident in incidents:
        repo.save(incident)
    return incidents


def test_overview_page(client, sample_devices, sample_incidents):
    """Test overview page loads with My Connection dashboard."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"MCP Network Diagnostics" in response.content
    # Overview now shows "My Connection" with connection cards (Gateway, DNS, Internet)
    assert b"Gateway" in response.content or b"My Connection" in response.content


def test_devices_page(client, sample_devices):
    """Test devices page loads."""
    response = client.get("/devices")
    assert response.status_code == 200
    assert b"Router-1" in response.content
    assert b"Router-2" in response.content


def test_device_detail_page(client, sample_devices):
    """Test device detail page."""
    response = client.get("/devices/R1")
    assert response.status_code == 200
    assert b"Router-1" in response.content
    assert b"simulated" in response.content


def test_device_not_found(client):
    """Test device detail with non-existent device."""
    response = client.get("/devices/NONEXISTENT")
    assert response.status_code == 200
    assert b"Error" in response.content or b"not found" in response.content.lower()


def test_incidents_page(client, sample_incidents):
    """Test incidents page loads."""
    response = client.get("/incidents")
    assert response.status_code == 200
    assert b"INC-001" in response.content
    assert b"High CPU" in response.content


def test_intents_page(client):
    """Test intents page loads."""
    response = client.get("/intents")
    assert response.status_code == 200
    assert b"Monitoring Intents" in response.content


def test_settings_page(client):
    """Test settings page loads."""
    response = client.get("/settings")
    assert response.status_code == 200
    assert b"Settings" in response.content


def test_connection_partial(client):
    """Test HTMX partial for connection status."""
    response = client.get("/partials/connection")
    assert response.status_code == 200
    # Should be a fragment, not full page
    assert b"<html" not in response.content


def test_connection_partial_structure(client):
    """Test connection partial includes consumer-friendly sections."""
    response = client.get("/partials/connection")
    assert response.status_code == 200
    content = response.content
    assert b"My Connection" in content
    assert b"WiFi" in content
    assert b"Local Network" in content or b"Gateway" in content
    assert b"DNS" in content
    assert b"Internet" in content
    # Overall status is one of healthy / warning / critical / degraded (template capitalizes)
    lower = content.lower()
    assert any(s in lower for s in (b"healthy", b"warning", b"critical", b"degraded"))


def test_static_files(client):
    """Test static files are served."""
    response = client.get("/static/style.css")
    assert response.status_code == 200


def test_health_check_endpoint(client, sample_devices, sample_incidents):
    """Test health metrics calculation."""
    # Overview page includes health score
    response = client.get("/")
    assert response.status_code == 200
    # Should show some health percentage
    assert b"%" in response.content


def test_status_dev_endpoint(client):
    """Test /status/dev returns JSON with config info for developers."""
    response = client.get("/status/dev")
    assert response.status_code == 200
    data = response.json()
    # Required fields for developers
    assert "transport" in data
    assert "mcp_transports_available" in data
    assert "collector_mode" in data
    assert "features" in data
    assert "rate_limits" in data
    # Features should include key capabilities
    assert "agent" in data["features"]
    assert "baselines" in data["features"]
    assert "rate_limiting" in data["features"]
    # Rate limits should have values
    assert data["rate_limits"]["consumer_per_minute"] > 0
    assert data["rate_limits"]["global_per_minute"] > 0


def test_guest_session_shows_using_as_guest(client):
    """Test that after receiving session cookie, next request shows 'Using as guest'."""
    r1 = client.get("/")
    assert r1.status_code == 200
    r2 = client.get("/")
    assert r2.status_code == 200
    assert b"Using as guest" in r2.content


def test_consumer_rate_limit_overview_returns_429(client, monkeypatch):
    """Test overview returns 429 when consumer rate limit is exceeded."""
    def deny(_identity):
        return False, 60.0

    monkeypatch.setattr(
        "mcp_network.dashboard.routes.overview.check_consumer_rate_limit",
        deny,
    )
    response = client.get("/")
    assert response.status_code == 429
    assert b"Rate limit" in response.content or b"rate limit" in response.content.lower()


def test_consumer_rate_limit_tools_invoke_returns_429(client, monkeypatch):
    """Test tools invoke returns 429 when consumer rate limit is exceeded."""
    def deny(_identity):
        return False, 60.0

    monkeypatch.setattr(
        "mcp_network.dashboard.routes.tools.check_consumer_rate_limit",
        deny,
    )
    response = client.post(
        "/tools/invoke",
        data={"tool_id": "check_my_connection"},
    )
    assert response.status_code == 429
    assert b"Rate limit" in response.content or b"rate limit" in response.content.lower()


def test_baseline_storage_per_identity(monkeypatch, tmp_path):
    """Test baseline storage is isolated per consumer identity (tenant)."""
    from mcp_network.storage.tenant import set_tenant_id
    from mcp_network.tools import _get_baseline_storage

    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    set_tenant_id("guest_alpha")
    storage_a = _get_baseline_storage()
    set_tenant_id("guest_beta")
    storage_b = _get_baseline_storage()

    set_tenant_id("default")  # Reset to default

    assert storage_a.storage_path != storage_b.storage_path
    assert "guest_alpha" in storage_a.storage_path or "alpha" in storage_a.storage_path
    assert "guest_beta" in storage_b.storage_path or "beta" in storage_b.storage_path


# ============================================================================
# Session Secret Tests
# ============================================================================

class TestSessionSecret:
    """Test session secret behavior in production vs development."""

    def test_production_without_secret_raises(self, monkeypatch):
        """Production mode without MCP_NETWORK_SESSION_SECRET raises RuntimeError."""
        monkeypatch.setenv("MCP_NETWORK_ENV", "production")
        monkeypatch.delenv("MCP_NETWORK_SESSION_SECRET", raising=False)

        # Force reimport to pick up env changes
        import importlib
        from mcp_network.dashboard import session
        importlib.reload(session)

        with pytest.raises(RuntimeError, match="MCP_NETWORK_SESSION_SECRET"):
            session._get_secret()

    def test_development_with_fallback_works(self, monkeypatch):
        """Development mode uses hardcoded fallback."""
        monkeypatch.setenv("MCP_NETWORK_ENV", "development")
        monkeypatch.delenv("MCP_NETWORK_SESSION_SECRET", raising=False)

        import importlib
        from mcp_network.dashboard import session
        importlib.reload(session)

        secret = session._get_secret()
        assert isinstance(secret, bytes)
        assert len(secret) == 32  # SHA-256 output

    def test_explicit_secret_used(self, monkeypatch):
        """Explicit secret env var is used when set."""
        monkeypatch.setenv("MCP_NETWORK_SESSION_SECRET", "my-super-secret-key")
        monkeypatch.setenv("MCP_NETWORK_ENV", "production")

        import importlib
        from mcp_network.dashboard import session
        importlib.reload(session)

        secret = session._get_secret()
        assert isinstance(secret, bytes)
        assert len(secret) == 32

    def test_valid_secret_generates_verifiable_cookies(self, monkeypatch):
        """Session cookies created with valid secret can be verified."""
        monkeypatch.setenv("MCP_NETWORK_SESSION_SECRET", "test-secret-123")
        monkeypatch.setenv("MCP_NETWORK_ENV", "production")

        import importlib
        from mcp_network.dashboard import session
        importlib.reload(session)

        identity, cookie = session.create_session_cookie_value()
        assert identity.startswith("guest_")

        verified = session.verify_session_cookie(cookie)
        assert verified == identity
