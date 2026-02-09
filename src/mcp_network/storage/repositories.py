"""Repository layer for data access patterns."""

from datetime import datetime, timedelta
from typing import Optional, List
from .database import Database
from .models import Device, Metric, Incident, Intent, ConfigSnapshot, AuditEvent


class DeviceRepository:
    """Repository for device data."""

    def __init__(self, db: Database):
        self.db = db

    def save(self, device: Device):
        """Save or update device."""
        self.db.execute("""
            INSERT OR REPLACE INTO devices
            (id, name, device_type, collector_type, first_seen, last_seen, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, tuple(device.to_dict().values()))
        self.db.commit()

    def find_by_id(self, device_id: str) -> Optional[Device]:
        """Find device by ID."""
        cursor = self.db.execute(
            "SELECT * FROM devices WHERE id = ?",
            (device_id,)
        )
        row = cursor.fetchone()
        return Device.from_row(row) if row else None

    def find_all(self) -> List[Device]:
        """Get all devices."""
        cursor = self.db.execute("SELECT * FROM devices ORDER BY name")
        return [Device.from_row(row) for row in cursor.fetchall()]

    def update_last_seen(self, device_id: str, timestamp: datetime):
        """Update last seen timestamp."""
        self.db.execute(
            "UPDATE devices SET last_seen = ? WHERE id = ?",
            (timestamp.isoformat(), device_id)
        )
        self.db.commit()


class MetricRepository:
    """Repository for metric data."""

    def __init__(self, db: Database):
        self.db = db

    def save(self, metric: Metric):
        """Save a metric."""
        self.db.execute("""
            INSERT INTO metrics (device_id, metric_name, value, timestamp)
            VALUES (?, ?, ?, ?)
        """, tuple(metric.to_dict().values()))
        self.db.commit()

    def save_batch(self, metrics: List[Metric]):
        """Save multiple metrics efficiently."""
        self.db.executemany(
            "INSERT INTO metrics (device_id, metric_name, value, timestamp) VALUES (?, ?, ?, ?)",
            [tuple(m.to_dict().values()) for m in metrics]
        )

    def query(
        self,
        device_id: str,
        metric_name: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
    ) -> List[Metric]:
        """Query metrics for a device in a time range."""
        cursor = self.db.execute("""
            SELECT * FROM metrics
            WHERE device_id = ? AND metric_name = ?
            AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (device_id, metric_name, start_time.isoformat(), end_time.isoformat(), limit))

        return [Metric.from_row(row) for row in cursor.fetchall()]

    def get_latest(self, device_id: str, metric_name: str) -> Optional[Metric]:
        """Get latest metric value."""
        cursor = self.db.execute("""
            SELECT * FROM metrics
            WHERE device_id = ? AND metric_name = ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (device_id, metric_name))

        row = cursor.fetchone()
        return Metric.from_row(row) if row else None

    def delete_old(self, days: int = 90):
        """Delete metrics older than N days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        self.db.execute("DELETE FROM metrics WHERE timestamp < ?", (cutoff,))
        self.db.commit()


class IncidentRepository:
    """Repository for incident data."""

    def __init__(self, db: Database):
        self.db = db

    def save(self, incident: Incident):
        """Save or update incident."""
        self.db.execute("""
            INSERT OR REPLACE INTO incidents
            (id, created_at, resolved_at, severity, summary, root_cause,
             affected_devices, causal_chain, actions_taken)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, tuple(incident.to_dict().values()))
        self.db.commit()

    def find_by_id(self, incident_id: str) -> Optional[Incident]:
        """Find incident by ID."""
        cursor = self.db.execute(
            "SELECT * FROM incidents WHERE id = ?",
            (incident_id,)
        )
        row = cursor.fetchone()
        return Incident.from_row(row) if row else None

    def find_active(self) -> List[Incident]:
        """Get all active (unresolved) incidents."""
        cursor = self.db.execute("""
            SELECT * FROM incidents
            WHERE resolved_at IS NULL
            ORDER BY created_at DESC
        """)
        return [Incident.from_row(row) for row in cursor.fetchall()]

    def find_recent(self, days: int = 7, limit: int = 100) -> List[Incident]:
        """Get recent incidents."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.db.execute("""
            SELECT * FROM incidents
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (cutoff, limit))
        return [Incident.from_row(row) for row in cursor.fetchall()]

    def find_by_device(self, device_id: str, days: int = 30) -> List[Incident]:
        """Get incidents affecting a specific device."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.db.execute("""
            SELECT * FROM incidents
            WHERE created_at >= ?
            AND affected_devices LIKE ?
            ORDER BY created_at DESC
        """, (cutoff, f'%"{device_id}"%'))
        return [Incident.from_row(row) for row in cursor.fetchall()]

    def resolve(self, incident_id: str, resolved_at: datetime):
        """Mark incident as resolved."""
        self.db.execute(
            "UPDATE incidents SET resolved_at = ? WHERE id = ?",
            (resolved_at.isoformat(), incident_id)
        )
        self.db.commit()


class IntentRepository:
    """Repository for intent data."""

    def __init__(self, db: Database):
        self.db = db

    def save(self, intent: Intent):
        """Save or update intent."""
        self.db.execute("""
            INSERT OR REPLACE INTO intents
            (id, natural_language, parsed_intent, created_at, created_by,
             active, last_checked, last_violated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, tuple(intent.to_dict().values()))
        self.db.commit()

    def find_by_id(self, intent_id: str) -> Optional[Intent]:
        """Find intent by ID."""
        cursor = self.db.execute(
            "SELECT * FROM intents WHERE id = ?",
            (intent_id,)
        )
        row = cursor.fetchone()
        return Intent.from_row(row) if row else None

    def find_active(self) -> List[Intent]:
        """Get all active intents."""
        cursor = self.db.execute("""
            SELECT * FROM intents
            WHERE active = 1
            ORDER BY created_at DESC
        """)
        return [Intent.from_row(row) for row in cursor.fetchall()]

    def find_all(self) -> List[Intent]:
        """Get all intents."""
        cursor = self.db.execute("""
            SELECT * FROM intents
            ORDER BY created_at DESC
        """)
        return [Intent.from_row(row) for row in cursor.fetchall()]

    def deactivate(self, intent_id: str):
        """Deactivate an intent."""
        self.db.execute(
            "UPDATE intents SET active = 0 WHERE id = ?",
            (intent_id,)
        )
        self.db.commit()

    def update_check_time(self, intent_id: str, timestamp: datetime):
        """Update last checked timestamp."""
        self.db.execute(
            "UPDATE intents SET last_checked = ? WHERE id = ?",
            (timestamp.isoformat(), intent_id)
        )
        self.db.commit()

    def update_violation_time(self, intent_id: str, timestamp: datetime):
        """Update last violated timestamp."""
        self.db.execute(
            "UPDATE intents SET last_violated = ? WHERE id = ?",
            (timestamp.isoformat(), intent_id)
        )
        self.db.commit()


class ConfigRepository:
    """Repository for configuration snapshots."""

    def __init__(self, db: Database):
        self.db = db

    def save(self, snapshot: ConfigSnapshot):
        """Save a config snapshot."""
        self.db.execute("""
            INSERT INTO config_snapshots (device_id, config_hash, config_text, captured_at)
            VALUES (?, ?, ?, ?)
        """, tuple(snapshot.to_dict().values()))
        self.db.commit()

    def find_latest(self, device_id: str) -> Optional[ConfigSnapshot]:
        """Get latest config snapshot for device."""
        cursor = self.db.execute("""
            SELECT * FROM config_snapshots
            WHERE device_id = ?
            ORDER BY captured_at DESC
            LIMIT 1
        """, (device_id,))

        row = cursor.fetchone()
        return ConfigSnapshot.from_row(row) if row else None

    def find_by_time_range(
        self,
        device_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> List[ConfigSnapshot]:
        """Find config snapshots in a time range."""
        cursor = self.db.execute("""
            SELECT * FROM config_snapshots
            WHERE device_id = ?
            AND captured_at BETWEEN ? AND ?
            ORDER BY captured_at DESC
        """, (device_id, start_time.isoformat(), end_time.isoformat()))

        return [ConfigSnapshot.from_row(row) for row in cursor.fetchall()]

    def find_changes(self, device_id: str, days: int = 30) -> List[ConfigSnapshot]:
        """Find config changes (where hash changed)."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.db.execute("""
            SELECT * FROM config_snapshots
            WHERE device_id = ? AND captured_at >= ?
            ORDER BY captured_at DESC
        """, (device_id, cutoff))

        snapshots = [ConfigSnapshot.from_row(row) for row in cursor.fetchall()]

        # Filter to only changes (hash differs from previous)
        changes = []
        prev_hash = None
        for snapshot in snapshots:
            if snapshot.config_hash != prev_hash:
                changes.append(snapshot)
                prev_hash = snapshot.config_hash

        return changes


class AuditRepository:
    """Repository for audit events."""

    def __init__(self, db: Database):
        self.db = db

    def save(self, event: AuditEvent):
        """Save an audit event."""
        self.db.execute("""
            INSERT INTO audit_events
            (timestamp, event_type, key_id, tool, parameters, result,
             duration_ms, event_hash, client_ip)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, tuple(event.to_dict().values()))
        self.db.commit()

    def find_recent(self, limit: int = 100) -> List[AuditEvent]:
        """Get recent audit events."""
        cursor = self.db.execute("""
            SELECT * FROM audit_events
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        return [AuditEvent.from_row(row) for row in cursor.fetchall()]

    def find_by_key(self, key_id: str, limit: int = 100) -> List[AuditEvent]:
        """Get audit events for a specific API key."""
        cursor = self.db.execute("""
            SELECT * FROM audit_events
            WHERE key_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (key_id, limit))
        return [AuditEvent.from_row(row) for row in cursor.fetchall()]

    def find_by_time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
    ) -> List[AuditEvent]:
        """Find audit events in a time range."""
        cursor = self.db.execute("""
            SELECT * FROM audit_events
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (start_time.isoformat(), end_time.isoformat(), limit))
        return [AuditEvent.from_row(row) for row in cursor.fetchall()]

    def delete_old(self, days: int = 90):
        """Delete audit events older than N days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        self.db.execute("DELETE FROM audit_events WHERE timestamp < ?", (cutoff,))
        self.db.commit()
