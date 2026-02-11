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
