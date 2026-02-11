"""Command-line interface for common operations."""

import sys
from .storage.database import get_database
from .storage.repositories import (
    DeviceRepository,
    IncidentRepository,
    IntentRepository,
)


def print_devices():
    """List all monitored devices."""
    db = get_database()
    repo = DeviceRepository(db)
    devices = repo.find_all()

    if not devices:
        print("No devices found.")
        return

    print(f"\n{'ID':<15} {'Name':<20} {'Type':<15} {'Last Seen':<25}")
    print("-" * 75)
    for device in devices:
        print(
            f"{device.id:<15} {device.name:<20} {device.device_type:<15} "
            f"{device.last_seen.strftime('%Y-%m-%d %H:%M:%S'):<25}"
        )
    print(f"\nTotal: {len(devices)} devices\n")


def print_incidents(days: int = 7):
    """Show recent incidents."""
    db = get_database()
    repo = IncidentRepository(db)
    incidents = repo.find_recent(days=days, limit=50)

    if not incidents:
        print(f"No incidents in the last {days} days.")
        return

    print(f"\nIncidents (last {days} days):\n")
    for incident in incidents:
        status = "RESOLVED" if incident.resolved_at else "ACTIVE"
        print(f"[{incident.severity.upper()}] {status} - {incident.summary}")
        print(f"  ID: {incident.id}")
        print(f"  Created: {incident.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        if incident.resolved_at:
            print(f"  Resolved: {incident.resolved_at.strftime('%Y-%m-%d %H:%M:%S')}")
        if incident.affected_devices:
            print(f"  Devices: {', '.join(incident.affected_devices)}")
        print()

    print(f"Total: {len(incidents)} incidents\n")


def print_intents():
    """List active monitoring intents."""
    db = get_database()
    repo = IntentRepository(db)
    intents = repo.find_active()

    if not intents:
        print("No active intents.")
        return

    print("\nActive Intents:\n")
    for intent in intents:
        print(f"[{intent.id}] {intent.natural_language}")
        if intent.last_checked:
            print(f"  Last checked: {intent.last_checked.strftime('%Y-%m-%d %H:%M:%S')}")
        if intent.last_violated:
            print(f"  Last violated: {intent.last_violated.strftime('%Y-%m-%d %H:%M:%S')}")
        print()

    print(f"Total: {len(intents)} intents\n")


def print_stats():
    """Show database statistics."""
    db = get_database()
    stats = db.get_stats()

    print("\nDatabase Statistics:\n")
    print(f"  Devices:         {stats['devices']:>10}")
    print(f"  Metrics:         {stats['metrics']:>10}")
    print(f"  Incidents:       {stats['incidents']:>10}")
    print(f"  Intents:         {stats['intents']:>10}")
    print(f"  Config Snapshots:{stats['config_snapshots']:>10}")
    print(f"  Audit Events:    {stats['audit_events']:>10}")
    print(f"\n  Database Size:   {stats['file_size_mb']:>10.2f} MB\n")


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m mcp_network.cli <command>")
        print("\nCommands:")
        print("  devices              List all devices")
        print("  incidents [days]     Show recent incidents (default: 7 days)")
        print("  intents              List active intents")
        print("  stats                Show database statistics")
        sys.exit(1)

    command = sys.argv[1]

    try:
        if command == "devices":
            print_devices()
        elif command == "incidents":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            print_incidents(days)
        elif command == "intents":
            print_intents()
        elif command == "stats":
            print_stats()
        else:
            print(f"Unknown command: {command}")
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
