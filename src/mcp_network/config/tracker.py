"""Track configuration changes and correlate with anomalies."""
from __future__ import annotations

import hashlib
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional


@dataclass
class ConfigSnapshot:
    """Single configuration snapshot."""
    device_id: str
    config_hash: str
    timestamp: float
    config_text: Optional[str] = None  # Store full config for diff
    config_summary: Optional[str] = None  # Brief description of changes

    @property
    def age_seconds(self) -> float:
        """Age of this snapshot in seconds."""
        return time.time() - self.timestamp


@dataclass
class ConfigChange:
    """Detected configuration change event."""
    device_id: str
    change_time: float
    old_hash: str
    new_hash: str
    description: str = ""

    @property
    def age_seconds(self) -> float:
        """Time since this change occurred."""
        return time.time() - self.change_time


class ConfigTracker:
    """Track configuration snapshots and detect changes."""

    def __init__(self, max_snapshots_per_device: int = 100):
        """Initialize config tracker.

        Args:
            max_snapshots_per_device: Max snapshots to retain per device
        """
        self.snapshots: dict[str, deque[ConfigSnapshot]] = {}
        self.changes: dict[str, deque[ConfigChange]] = {}
        self.max_snapshots = max_snapshots_per_device
        self.max_changes = 50

    def _hash_config(self, config_text: str) -> str:
        """Compute hash of configuration text."""
        return hashlib.sha256(config_text.encode()).hexdigest()[:16]

    def add_snapshot(
        self,
        device_id: str,
        config_text: str,
        timestamp: Optional[float] = None,
    ) -> Optional[ConfigChange]:
        """Add a config snapshot and detect changes.

        Returns:
            ConfigChange if a change was detected, else None
        """
        if timestamp is None:
            timestamp = time.time()

        config_hash = self._hash_config(config_text)

        # Initialize queues if needed
        if device_id not in self.snapshots:
            self.snapshots[device_id] = deque(maxlen=self.max_snapshots)
        if device_id not in self.changes:
            self.changes[device_id] = deque(maxlen=self.max_changes)

        # Check for changes
        previous_snapshot = self.snapshots[device_id][-1] if self.snapshots[device_id] else None
        change_detected = None

        if previous_snapshot and previous_snapshot.config_hash != config_hash:
            # Config changed!
            change_detected = ConfigChange(
                device_id=device_id,
                change_time=timestamp,
                old_hash=previous_snapshot.config_hash,
                new_hash=config_hash,
                description=f"Config changed on {device_id}",
            )
            self.changes[device_id].append(change_detected)

        # Store snapshot
        snapshot = ConfigSnapshot(
            device_id=device_id,
            config_hash=config_hash,
            timestamp=timestamp,
            config_text=config_text,
        )
        self.snapshots[device_id].append(snapshot)

        return change_detected

    def get_latest_snapshot(self, device_id: str) -> Optional[ConfigSnapshot]:
        """Get the most recent config snapshot for a device."""
        snapshots = self.snapshots.get(device_id)
        if snapshots:
            return snapshots[-1]
        return None

    def get_snapshot_at_time(
        self,
        device_id: str,
        target_time: float,
    ) -> Optional[ConfigSnapshot]:
        """Get the config snapshot closest to a target time."""
        snapshots = self.snapshots.get(device_id)
        if not snapshots:
            return None

        # Find snapshot with timestamp <= target_time, closest to target
        candidates = [s for s in snapshots if s.timestamp <= target_time]
        if not candidates:
            return None

        return max(candidates, key=lambda s: s.timestamp)

    def get_changes_in_window(
        self,
        device_id: str,
        window_seconds: float,
    ) -> list[ConfigChange]:
        """Get all config changes within the last N seconds."""
        changes = self.changes.get(device_id, [])
        cutoff_time = time.time() - window_seconds
        return [c for c in changes if c.change_time >= cutoff_time]

    def get_all_recent_changes(self, window_seconds: float) -> list[ConfigChange]:
        """Get all config changes across all devices within window."""
        cutoff_time = time.time() - window_seconds
        all_changes = []
        for device_changes in self.changes.values():
            all_changes.extend(c for c in device_changes if c.change_time >= cutoff_time)
        return sorted(all_changes, key=lambda c: c.change_time, reverse=True)

    def diff_configs(
        self,
        device_id: str,
        time_a: float,
        time_b: float,
    ) -> Optional[str]:
        """Generate diff between configs at two points in time.

        Returns:
            Unified diff string, or None if snapshots not found
        """
        snap_a = self.get_snapshot_at_time(device_id, time_a)
        snap_b = self.get_snapshot_at_time(device_id, time_b)

        if not snap_a or not snap_b:
            return None

        if snap_a.config_hash == snap_b.config_hash:
            return "No changes detected"

        # Simple line-by-line diff
        if snap_a.config_text and snap_b.config_text:
            lines_a = snap_a.config_text.splitlines()
            lines_b = snap_b.config_text.splitlines()

            # Basic diff: show added/removed lines
            diff_lines = []
            diff_lines.append(f"--- Config at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(snap_a.timestamp))}")
            diff_lines.append(f"+++ Config at {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(snap_b.timestamp))}")

            # Simple set-based diff
            set_a = set(lines_a)
            set_b = set(lines_b)
            removed = set_a - set_b
            added = set_b - set_a

            for line in sorted(removed):
                diff_lines.append(f"- {line}")
            for line in sorted(added):
                diff_lines.append(f"+ {line}")

            return "\n".join(diff_lines)

        return f"Config hash changed: {snap_a.config_hash} → {snap_b.config_hash}"

    def has_recent_change(
        self,
        device_id: str,
        window_seconds: float,
    ) -> bool:
        """Check if device had a config change in the last N seconds."""
        return len(self.get_changes_in_window(device_id, window_seconds)) > 0

    def get_change_history(
        self,
        device_id: str,
        limit: int = 10,
    ) -> list[ConfigChange]:
        """Get recent config changes for a device."""
        changes = self.changes.get(device_id, [])
        return list(changes)[-limit:]


# Global singleton
_config_tracker: Optional[ConfigTracker] = None


def get_config_tracker() -> ConfigTracker:
    """Get the global config tracker instance."""
    global _config_tracker
    if _config_tracker is None:
        _config_tracker = ConfigTracker()
    return _config_tracker
