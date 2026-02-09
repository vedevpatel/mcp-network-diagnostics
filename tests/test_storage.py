"""Tests for persistent storage layer."""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mcp_network.storage import (
    Database,
    Device,
    Metric,
    Incident,
    Intent,
    ConfigSnapshot,
    AuditEvent,
    DeviceRepository,
    MetricRepository,
    IncidentRepository,
    IntentRepository,
    ConfigRepository,
    AuditRepository,
)


@pytest.fixture
def test_db(tmp_path):
    """Create test database."""
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    yield db
    db.close()


class TestDatabase:
    """Tests for database management."""

    def test_database_initialization(self, tmp_path):
        """Test database creates schema."""
        db_path = tmp_path / "test.db"
        db = Database(str(db_path))

        # Verify tables exist
        cursor = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {
            "devices", "metrics", "incidents", "intents",
            "config_snapshots", "audit_events"
        }
        assert expected_tables.issubset(tables)

        db.close()

    def test_database_stats(self, test_db):
        """Test database statistics."""
        stats = test_db.get_stats()

        assert "devices" in stats
        assert "metrics" in stats
        assert "file_size_mb" in stats
        assert stats["devices"] == 0  # Empty database


class TestDeviceRepository:
    """Tests for device repository."""

    def test_save_and_find_device(self, test_db):
        """Test saving and retrieving a device."""
        repo = DeviceRepository(test_db)

        device = Device(
            id="R1",
            name="Router 1",
            device_type="router",
            collector_type="simulated",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            metadata={"vendor": "Cisco"},
        )

        repo.save(device)
        retrieved = repo.find_by_id("R1")

        assert retrieved is not None
        assert retrieved.id == "R1"
        assert retrieved.name == "Router 1"
        assert retrieved.metadata["vendor"] == "Cisco"

    def test_find_all_devices(self, test_db):
        """Test finding all devices."""
        repo = DeviceRepository(test_db)

        for i in range(3):
            device = Device(
                id=f"R{i}",
                name=f"Router {i}",
                device_type="router",
                collector_type="simulated",
                first_seen=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc),
                metadata={},
            )
            repo.save(device)

        devices = repo.find_all()
        assert len(devices) == 3

    def test_update_last_seen(self, test_db):
        """Test updating last seen timestamp."""
        repo = DeviceRepository(test_db)

        device = Device(
            id="R1",
            name="Router 1",
            device_type="router",
            collector_type="simulated",
            first_seen=datetime.now(timezone.utc),
            last_seen=datetime.now(timezone.utc),
            metadata={},
        )
        repo.save(device)

        new_time = datetime.now(timezone.utc) + timedelta(hours=1)
        repo.update_last_seen("R1", new_time)

        retrieved = repo.find_by_id("R1")
        assert retrieved.last_seen.replace(microsecond=0) == new_time.replace(microsecond=0)


class TestMetricRepository:
    """Tests for metric repository."""

    def test_save_and_query_metrics(self, test_db):
        """Test saving and querying metrics."""
        repo = MetricRepository(test_db)

        now = datetime.now(timezone.utc)
        metrics = []
        for i in range(10):
            metric = Metric(
                device_id="R1",
                metric_name="cpu",
                value=50.0 + i,
                timestamp=now - timedelta(minutes=10-i),
            )
            metrics.append(metric)

        repo.save_batch(metrics)

        # Query last 5 minutes
        results = repo.query(
            "R1",
            "cpu",
            now - timedelta(minutes=5),
            now,
            limit=100,
        )

        assert len(results) == 5  # Last 5 minutes

    def test_get_latest_metric(self, test_db):
        """Test getting latest metric value."""
        repo = MetricRepository(test_db)

        now = datetime.now(timezone.utc)
        for i in range(3):
            metric = Metric(
                device_id="R1",
                metric_name="cpu",
                value=float(i),
                timestamp=now - timedelta(minutes=3-i),
            )
            repo.save(metric)

        latest = repo.get_latest("R1", "cpu")
        assert latest is not None
        assert latest.value == 2.0  # Most recent


class TestIncidentRepository:
    """Tests for incident repository."""

    def test_save_and_find_incident(self, test_db):
        """Test saving and retrieving an incident."""
        repo = IncidentRepository(test_db)

        incident = Incident(
            id="inc_001",
            created_at=datetime.now(timezone.utc),
            severity="critical",
            summary="High CPU on R1",
            root_cause="Configuration issue",
            affected_devices=["R1"],
        )

        repo.save(incident)
        retrieved = repo.find_by_id("inc_001")

        assert retrieved is not None
        assert retrieved.severity == "critical"
        assert "R1" in retrieved.affected_devices

    def test_find_active_incidents(self, test_db):
        """Test finding active (unresolved) incidents."""
        repo = IncidentRepository(test_db)

        # Create resolved incident
        resolved = Incident(
            id="inc_001",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            resolved_at=datetime.now(timezone.utc) - timedelta(hours=1),
            severity="warning",
            summary="Resolved issue",
        )
        repo.save(resolved)

        # Create active incident
        active = Incident(
            id="inc_002",
            created_at=datetime.now(timezone.utc),
            severity="critical",
            summary="Active issue",
        )
        repo.save(active)

        active_incidents = repo.find_active()
        assert len(active_incidents) == 1
        assert active_incidents[0].id == "inc_002"

    def test_resolve_incident(self, test_db):
        """Test resolving an incident."""
        repo = IncidentRepository(test_db)

        incident = Incident(
            id="inc_001",
            created_at=datetime.now(timezone.utc),
            severity="critical",
            summary="Test incident",
        )
        repo.save(incident)

        resolve_time = datetime.now(timezone.utc)
        repo.resolve("inc_001", resolve_time)

        retrieved = repo.find_by_id("inc_001")
        assert retrieved.resolved_at is not None


class TestIntentRepository:
    """Tests for intent repository."""

    def test_save_and_find_intent(self, test_db):
        """Test saving and retrieving an intent."""
        repo = IntentRepository(test_db)

        intent = Intent(
            id="intent_001",
            natural_language="Zoom should never lag",
            parsed_intent={"target": "zoom.us", "metric": "latency", "threshold": 100},
            created_at=datetime.now(timezone.utc),
            active=True,
        )

        repo.save(intent)
        retrieved = repo.find_by_id("intent_001")

        assert retrieved is not None
        assert retrieved.natural_language == "Zoom should never lag"
        assert retrieved.active

    def test_find_active_intents(self, test_db):
        """Test finding only active intents."""
        repo = IntentRepository(test_db)

        # Create active intent
        active = Intent(
            id="intent_001",
            natural_language="Test 1",
            parsed_intent={},
            created_at=datetime.now(timezone.utc),
            active=True,
        )
        repo.save(active)

        # Create inactive intent
        inactive = Intent(
            id="intent_002",
            natural_language="Test 2",
            parsed_intent={},
            created_at=datetime.now(timezone.utc),
            active=False,
        )
        repo.save(inactive)

        active_intents = repo.find_active()
        assert len(active_intents) == 1
        assert active_intents[0].id == "intent_001"

    def test_deactivate_intent(self, test_db):
        """Test deactivating an intent."""
        repo = IntentRepository(test_db)

        intent = Intent(
            id="intent_001",
            natural_language="Test",
            parsed_intent={},
            created_at=datetime.now(timezone.utc),
            active=True,
        )
        repo.save(intent)

        repo.deactivate("intent_001")

        retrieved = repo.find_by_id("intent_001")
        assert not retrieved.active


class TestConfigRepository:
    """Tests for config snapshot repository."""

    def test_save_and_find_latest(self, test_db):
        """Test saving and retrieving latest config."""
        repo = ConfigRepository(test_db)

        now = datetime.now(timezone.utc)
        for i in range(3):
            snapshot = ConfigSnapshot(
                device_id="R1",
                config_hash=f"hash_{i}",
                config_text=f"config {i}",
                captured_at=now - timedelta(hours=3-i),
            )
            repo.save(snapshot)

        latest = repo.find_latest("R1")
        assert latest is not None
        assert latest.config_hash == "hash_2"  # Most recent

    def test_find_changes(self, test_db):
        """Test finding config changes."""
        repo = ConfigRepository(test_db)

        now = datetime.now(timezone.utc)

        # Same config twice
        for i in range(2):
            snapshot = ConfigSnapshot(
                device_id="R1",
                config_hash="hash_1",
                config_text="config 1",
                captured_at=now - timedelta(hours=5-i),
            )
            repo.save(snapshot)

        # Changed config
        snapshot = ConfigSnapshot(
            device_id="R1",
            config_hash="hash_2",
            config_text="config 2",
            captured_at=now - timedelta(hours=3),
        )
        repo.save(snapshot)

        # Same as previous
        snapshot = ConfigSnapshot(
            device_id="R1",
            config_hash="hash_2",
            config_text="config 2",
            captured_at=now - timedelta(hours=2),
        )
        repo.save(snapshot)

        changes = repo.find_changes("R1", days=30)
        # Should find 2 changes (hash_1 and hash_2)
        assert len(changes) >= 2


class TestAuditRepository:
    """Tests for audit event repository."""

    def test_save_and_find_recent(self, test_db):
        """Test saving and retrieving audit events."""
        repo = AuditRepository(test_db)

        now = datetime.now(timezone.utc)
        for i in range(5):
            event = AuditEvent(
                timestamp=now - timedelta(minutes=5-i),
                event_type="tool_call",
                key_id="test_key",
                tool="list_devices",
                result="success",
            )
            repo.save(event)

        recent = repo.find_recent(limit=3)
        assert len(recent) == 3

    def test_find_by_key(self, test_db):
        """Test finding events by API key."""
        repo = AuditRepository(test_db)

        now = datetime.now(timezone.utc)
        event1 = AuditEvent(
            timestamp=now,
            event_type="tool_call",
            key_id="key_1",
            result="success",
        )
        repo.save(event1)

        event2 = AuditEvent(
            timestamp=now,
            event_type="tool_call",
            key_id="key_2",
            result="success",
        )
        repo.save(event2)

        key1_events = repo.find_by_key("key_1")
        assert len(key1_events) == 1
        assert key1_events[0].key_id == "key_1"
