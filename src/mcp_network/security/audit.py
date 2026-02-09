"""Audit logging with tamper-evident chain."""

import hashlib
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class AuditEvent:
    """A single audit log event."""
    timestamp: float
    event_type: str  # "auth", "tool_call", "error", "config_change", "rate_limit"
    key_id: Optional[str]
    role: Optional[str]
    tool: Optional[str]
    parameters: Optional[dict]
    result: str  # "success", "denied", "error"
    error_message: Optional[str]
    client_ip: Optional[str]
    duration_ms: Optional[float]
    # Chain hashing for tamper detection
    previous_hash: Optional[str] = None
    event_hash: Optional[str] = None


class AuditLogger:
    """Tamper-evident audit logger using hash chaining."""

    def __init__(self, log_dir: Optional[str] = None):
        """Initialize audit logger.

        Args:
            log_dir: Directory for audit logs. Defaults to ~/.mcp_network/audit
        """
        if log_dir is None:
            log_dir = str(Path.home() / ".mcp_network" / "audit")

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.current_file: Optional[Path] = None
        self.last_hash: Optional[str] = None

        # Load last hash from most recent log
        self._load_last_hash()

    def log(self, event: AuditEvent):
        """Log an audit event with tamper-evident chaining.

        Args:
            event: Event to log
        """
        # Set previous hash
        event.previous_hash = self.last_hash

        # Calculate event hash (including previous hash for chaining)
        event_data = {
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "key_id": event.key_id,
            "role": event.role,
            "tool": event.tool,
            "parameters": event.parameters,
            "result": event.result,
            "error_message": event.error_message,
            "client_ip": event.client_ip,
            "duration_ms": event.duration_ms,
            "previous_hash": event.previous_hash,
        }
        event_json = json.dumps(event_data, sort_keys=True)
        event.event_hash = hashlib.sha256(event_json.encode()).hexdigest()

        # Update last hash for next event
        self.last_hash = event.event_hash

        # Write to daily log file
        log_file = self._get_log_file()
        with open(log_file, "a") as f:
            f.write(json.dumps(asdict(event)) + "\n")

    def log_auth(
        self,
        key_id: Optional[str],
        role: Optional[str],
        result: str,
        error: Optional[str] = None,
        client_ip: Optional[str] = None,
    ):
        """Log an authentication event.

        Args:
            key_id: API key ID (if provided)
            role: User role (if authenticated)
            result: "success" or "denied"
            error: Error message if denied
            client_ip: Client IP address
        """
        self.log(AuditEvent(
            timestamp=time.time(),
            event_type="auth",
            key_id=key_id,
            role=role,
            tool=None,
            parameters=None,
            result=result,
            error_message=error,
            client_ip=client_ip,
            duration_ms=None,
        ))

    def log_tool_call(
        self,
        key_id: Optional[str],
        role: Optional[str],
        tool: str,
        params: Optional[dict],
        result: str,
        error: Optional[str] = None,
        duration_ms: Optional[float] = None,
        client_ip: Optional[str] = None,
    ):
        """Log a tool call event.

        Args:
            key_id: API key ID
            role: User role
            tool: Tool name
            params: Tool parameters (will be sanitized)
            result: "success", "denied", or "error"
            error: Error message if applicable
            duration_ms: Execution duration
            client_ip: Client IP address
        """
        self.log(AuditEvent(
            timestamp=time.time(),
            event_type="tool_call",
            key_id=key_id,
            role=role,
            tool=tool,
            parameters=self._sanitize_params(params),
            result=result,
            error_message=error,
            client_ip=client_ip,
            duration_ms=duration_ms,
        ))

    def log_rate_limit(
        self,
        key_id: str,
        reason: str,
        retry_after: float,
        client_ip: Optional[str] = None,
    ):
        """Log a rate limit event.

        Args:
            key_id: API key ID
            reason: Rate limit reason
            retry_after: Seconds until retry allowed
            client_ip: Client IP address
        """
        self.log(AuditEvent(
            timestamp=time.time(),
            event_type="rate_limit",
            key_id=key_id,
            role=None,
            tool=None,
            parameters={"reason": reason, "retry_after": retry_after},
            result="denied",
            error_message=reason,
            client_ip=client_ip,
            duration_ms=None,
        ))

    def log_config_change(
        self,
        key_id: str,
        role: str,
        action: str,
        details: dict,
        client_ip: Optional[str] = None,
    ):
        """Log a configuration change event.

        Args:
            key_id: API key ID
            role: User role
            action: Action performed (e.g., "create_key", "revoke_key")
            details: Details of the change
            client_ip: Client IP address
        """
        self.log(AuditEvent(
            timestamp=time.time(),
            event_type="config_change",
            key_id=key_id,
            role=role,
            tool=None,
            parameters=details,
            result="success",
            error_message=None,
            client_ip=client_ip,
            duration_ms=None,
        ))

    def verify_chain(self, log_file: Optional[str] = None) -> tuple[bool, Optional[str]]:
        """Verify audit log chain integrity.

        Args:
            log_file: Specific log file to verify (or most recent if None)

        Returns:
            (valid, error_message) - True if chain is intact
        """
        if log_file is None:
            # Verify most recent log
            log_files = sorted(self.log_dir.glob("audit_*.jsonl"))
            if not log_files:
                return True, None  # No logs to verify
            log_file = str(log_files[-1])

        try:
            previous_hash = None
            line_num = 0

            with open(log_file) as f:
                for line in f:
                    line_num += 1
                    event_dict = json.loads(line)

                    # Check previous hash matches
                    if event_dict.get("previous_hash") != previous_hash:
                        return False, f"Chain broken at line {line_num}: previous_hash mismatch"

                    # Verify event hash
                    stored_hash = event_dict.get("event_hash")
                    if not stored_hash:
                        return False, f"Missing event_hash at line {line_num}"

                    # Recompute hash
                    event_data = {
                        k: v for k, v in event_dict.items()
                        if k not in ["event_hash"]
                    }
                    computed_hash = hashlib.sha256(
                        json.dumps(event_data, sort_keys=True).encode()
                    ).hexdigest()

                    if computed_hash != stored_hash:
                        return False, f"Hash mismatch at line {line_num}: event was tampered with"

                    previous_hash = stored_hash

            return True, None

        except FileNotFoundError:
            return False, f"Log file not found: {log_file}"
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON in log: {e}"
        except Exception as e:
            return False, f"Verification error: {e}"

    def search(
        self,
        key_id: Optional[str] = None,
        event_type: Optional[str] = None,
        result: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Search audit logs.

        Args:
            key_id: Filter by key ID
            event_type: Filter by event type
            result: Filter by result
            start_time: Start timestamp (inclusive)
            end_time: End timestamp (inclusive)
            limit: Maximum results to return

        Returns:
            List of matching audit events
        """
        events = []

        # Get all log files in time range
        log_files = sorted(self.log_dir.glob("audit_*.jsonl"))

        for log_file in log_files:
            with open(log_file) as f:
                for line in f:
                    if len(events) >= limit:
                        break

                    try:
                        event_dict = json.loads(line)

                        # Apply filters
                        if key_id and event_dict.get("key_id") != key_id:
                            continue
                        if event_type and event_dict.get("event_type") != event_type:
                            continue
                        if result and event_dict.get("result") != result:
                            continue

                        timestamp = event_dict.get("timestamp", 0)
                        if start_time and timestamp < start_time:
                            continue
                        if end_time and timestamp > end_time:
                            continue

                        events.append(AuditEvent(**event_dict))

                    except Exception:
                        continue  # Skip malformed entries

            if len(events) >= limit:
                break

        return events

    def _sanitize_params(self, params: Optional[dict]) -> Optional[dict]:
        """Remove sensitive data from parameters.

        Args:
            params: Parameters dict

        Returns:
            Sanitized parameters
        """
        if not params:
            return None

        sanitized = {}
        sensitive_keys = {"password", "secret", "key", "token", "credential", "api_key"}

        for k, v in params.items():
            if any(s in k.lower() for s in sensitive_keys):
                sanitized[k] = "[REDACTED]"
            else:
                sanitized[k] = v

        return sanitized

    def _get_log_file(self) -> Path:
        """Get current log file (daily rotation).

        Returns:
            Path to today's log file
        """
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d")
        return self.log_dir / f"audit_{date_str}.jsonl"

    def _load_last_hash(self):
        """Load the last hash from the most recent log file."""
        log_files = sorted(self.log_dir.glob("audit_*.jsonl"))
        if not log_files:
            return

        # Read last line of most recent log
        try:
            with open(log_files[-1]) as f:
                lines = f.readlines()
                if lines:
                    last_event = json.loads(lines[-1])
                    self.last_hash = last_event.get("event_hash")
        except Exception:
            pass  # Start fresh if we can't read
