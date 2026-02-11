"""Data models for persistent storage."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import json


@dataclass
class Device:
    """Device entity."""

    id: str
    name: str
    device_type: str
    collector_type: str
    first_seen: datetime
    last_seen: datetime
    metadata: dict
    tenant_id: str = "default"

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "name": self.name,
            "device_type": self.device_type,
            "collector_type": self.collector_type,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
            "metadata": json.dumps(self.metadata),
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_row(cls, row) -> "Device":
        """Create from database row."""
        return cls(
            id=row["id"],
            name=row["name"],
            device_type=row["device_type"],
            collector_type=row["collector_type"],
            first_seen=datetime.fromisoformat(row["first_seen"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default",
        )


@dataclass
class Metric:
    """Metric measurement."""

    device_id: str
    metric_name: str
    value: float
    timestamp: datetime
    id: Optional[int] = None
    tenant_id: str = "default"

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "device_id": self.device_id,
            "metric_name": self.metric_name,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_row(cls, row) -> "Metric":
        """Create from database row."""
        return cls(
            id=row["id"],
            device_id=row["device_id"],
            metric_name=row["metric_name"],
            value=row["value"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default",
        )


@dataclass
class Incident:
    """Network incident."""

    id: str
    created_at: datetime
    severity: str
    summary: str
    resolved_at: Optional[datetime] = None
    root_cause: Optional[str] = None
    affected_devices: Optional[list[str]] = None
    causal_chain: Optional[dict] = None
    actions_taken: Optional[list[str]] = None
    tenant_id: str = "default"

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "severity": self.severity,
            "summary": self.summary,
            "root_cause": self.root_cause,
            "affected_devices": json.dumps(self.affected_devices) if self.affected_devices else None,
            "causal_chain": json.dumps(self.causal_chain) if self.causal_chain else None,
            "actions_taken": json.dumps(self.actions_taken) if self.actions_taken else None,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_row(cls, row) -> "Incident":
        """Create from database row."""
        return cls(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            resolved_at=datetime.fromisoformat(row["resolved_at"]) if row["resolved_at"] else None,
            severity=row["severity"],
            summary=row["summary"],
            root_cause=row["root_cause"],
            affected_devices=json.loads(row["affected_devices"]) if row["affected_devices"] else None,
            causal_chain=json.loads(row["causal_chain"]) if row["causal_chain"] else None,
            actions_taken=json.loads(row["actions_taken"]) if row["actions_taken"] else None,
            tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default",
        )


@dataclass
class Intent:
    """Monitoring intent."""

    id: str
    natural_language: str
    parsed_intent: dict
    created_at: datetime
    created_by: Optional[str] = None
    active: bool = True
    last_checked: Optional[datetime] = None
    last_violated: Optional[datetime] = None
    tenant_id: str = "default"

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "natural_language": self.natural_language,
            "parsed_intent": json.dumps(self.parsed_intent),
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "active": 1 if self.active else 0,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
            "last_violated": self.last_violated.isoformat() if self.last_violated else None,
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_row(cls, row) -> "Intent":
        """Create from database row."""
        return cls(
            id=row["id"],
            natural_language=row["natural_language"],
            parsed_intent=json.loads(row["parsed_intent"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            created_by=row["created_by"],
            active=bool(row["active"]),
            last_checked=datetime.fromisoformat(row["last_checked"]) if row["last_checked"] else None,
            last_violated=datetime.fromisoformat(row["last_violated"]) if row["last_violated"] else None,
            tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default",
        )


@dataclass
class ConfigSnapshot:
    """Configuration snapshot."""

    device_id: str
    config_hash: str
    config_text: str
    captured_at: datetime
    id: Optional[int] = None
    tenant_id: str = "default"

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "device_id": self.device_id,
            "config_hash": self.config_hash,
            "config_text": self.config_text,
            "captured_at": self.captured_at.isoformat(),
            "tenant_id": self.tenant_id,
        }

    @classmethod
    def from_row(cls, row) -> "ConfigSnapshot":
        """Create from database row."""
        return cls(
            id=row["id"],
            device_id=row["device_id"],
            config_hash=row["config_hash"],
            config_text=row["config_text"],
            captured_at=datetime.fromisoformat(row["captured_at"]),
            tenant_id=row["tenant_id"] if "tenant_id" in row.keys() else "default",
        )


@dataclass
class AuditEvent:
    """Audit log event."""

    timestamp: datetime
    event_type: str
    result: str
    key_id: Optional[str] = None
    tool: Optional[str] = None
    parameters: Optional[dict] = None
    duration_ms: Optional[float] = None
    event_hash: Optional[str] = None
    client_ip: Optional[str] = None
    id: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "key_id": self.key_id,
            "tool": self.tool,
            "parameters": json.dumps(self.parameters) if self.parameters else None,
            "result": self.result,
            "duration_ms": self.duration_ms,
            "event_hash": self.event_hash,
            "client_ip": self.client_ip,
        }

    @classmethod
    def from_row(cls, row) -> "AuditEvent":
        """Create from database row."""
        return cls(
            id=row["id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            event_type=row["event_type"],
            key_id=row["key_id"],
            tool=row["tool"],
            parameters=json.loads(row["parameters"]) if row["parameters"] else None,
            result=row["result"],
            duration_ms=row["duration_ms"],
            event_hash=row["event_hash"],
            client_ip=row["client_ip"],
        )
