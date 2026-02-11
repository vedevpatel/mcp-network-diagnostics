"""Database connection and management."""

import sqlite3
from pathlib import Path
from typing import Optional
import json


class Database:
    """SQLite database manager for persistent storage.

    Uses SQLite by default for simplicity. Can be extended to PostgreSQL.
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file.
                    Defaults to ~/.mcp_network/metrics.db
        """
        if db_path is None:
            db_path = str(Path.home() / ".mcp_network" / "metrics.db")

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self.conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._initialize_schema()

    def _connect(self):
        """Establish database connection."""
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Access columns by name

        # Enable JSON support
        sqlite3.register_adapter(dict, lambda d: json.dumps(d))
        sqlite3.register_converter("JSONB", lambda s: json.loads(s.decode()))

    def _initialize_schema(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()

        # Devices table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                name TEXT,
                device_type TEXT,
                collector_type TEXT,
                first_seen TIMESTAMP,
                last_seen TIMESTAMP,
                metadata TEXT,
                tenant_id TEXT DEFAULT 'default'
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_devices_tenant
            ON devices(tenant_id)
        """)

        # Metrics table (time-series data)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                timestamp TIMESTAMP NOT NULL,
                tenant_id TEXT DEFAULT 'default',
                FOREIGN KEY (device_id) REFERENCES devices(id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_device_time
            ON metrics(device_id, timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_name_time
            ON metrics(metric_name, timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_metrics_tenant
            ON metrics(tenant_id, device_id, timestamp DESC)
        """)

        # Incidents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                created_at TIMESTAMP NOT NULL,
                resolved_at TIMESTAMP,
                severity TEXT NOT NULL,
                summary TEXT NOT NULL,
                root_cause TEXT,
                affected_devices TEXT,
                causal_chain TEXT,
                actions_taken TEXT,
                tenant_id TEXT DEFAULT 'default'
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_time
            ON incidents(created_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_incidents_tenant
            ON incidents(tenant_id, created_at DESC)
        """)

        # Intents table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS intents (
                id TEXT PRIMARY KEY,
                natural_language TEXT NOT NULL,
                parsed_intent TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                created_by TEXT,
                active BOOLEAN NOT NULL DEFAULT 1,
                last_checked TIMESTAMP,
                last_violated TIMESTAMP,
                tenant_id TEXT DEFAULT 'default'
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_intents_tenant
            ON intents(tenant_id)
        """)

        # Config snapshots table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                config_text TEXT NOT NULL,
                captured_at TIMESTAMP NOT NULL,
                tenant_id TEXT DEFAULT 'default',
                FOREIGN KEY (device_id) REFERENCES devices(id)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_config_device_time
            ON config_snapshots(device_id, captured_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_config_tenant
            ON config_snapshots(tenant_id, device_id, captured_at DESC)
        """)

        # Audit events table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP NOT NULL,
                event_type TEXT NOT NULL,
                key_id TEXT,
                tool TEXT,
                parameters TEXT,
                result TEXT NOT NULL,
                duration_ms REAL,
                event_hash TEXT,
                client_ip TEXT
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_time
            ON audit_events(timestamp DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_key
            ON audit_events(key_id)
        """)

        self.conn.commit()

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a query and return cursor.

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            Cursor with results
        """
        return self.conn.execute(query, params)

    def executemany(self, query: str, params_list: list[tuple]):
        """Execute query multiple times with different parameters.

        Args:
            query: SQL query string
            params_list: List of parameter tuples
        """
        self.conn.executemany(query, params_list)
        self.conn.commit()

    def commit(self):
        """Commit current transaction."""
        self.conn.commit()

    def rollback(self):
        """Rollback current transaction."""
        self.conn.rollback()

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def vacuum(self):
        """Optimize database (reclaim space, rebuild indexes)."""
        self.conn.execute("VACUUM")

    def get_stats(self) -> dict:
        """Get database statistics.

        Returns:
            Dict with table sizes and counts
        """
        cursor = self.conn.cursor()

        stats = {}
        tables = ["devices", "metrics", "incidents", "intents",
                  "config_snapshots", "audit_events"]

        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            stats[table] = cursor.fetchone()[0]

        # Database file size
        stats["file_size_mb"] = self.db_path.stat().st_size / (1024 * 1024)

        return stats


# Global database instance
_db_instance: Optional[Database] = None


def get_database(db_path: Optional[str] = None) -> Database:
    """Get or create global database instance.

    Args:
        db_path: Optional path to database file

    Returns:
        Database instance
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = Database(db_path)
    return _db_instance
