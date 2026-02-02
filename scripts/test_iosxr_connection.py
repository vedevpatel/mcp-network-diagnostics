#!/usr/bin/env python3
"""
Test SSH connection to Cisco DevNet IOS-XR sandbox.

This script verifies:
1. SSH connectivity to sandbox-iosxr-1.cisco.com
2. Netmiko IOS-XR device handler works
3. Show commands return expected output
4. Output format for future parsing

Usage:
    python scripts/test_iosxr_connection.py
"""

from netmiko import ConnectHandler
import sys


def main():
    """Test IOS-XR connection and commands."""

    # Device connection parameters
    device = {
        'device_type': 'cisco_xr',  # IMPORTANT: Not cisco_ios!
        'host': 'sandbox-iosxr-1.cisco.com',
        'username': 'vedevpatel',
        'password': 'If0g_-bS0R9aT8S',
        'port': 22,
        'timeout': 30,  # SSH connection timeout
        'session_timeout': 60,  # Command execution timeout
    }

    print("=" * 70)
    print("Cisco IOS-XR DevNet Sandbox - Connection Test")
    print("=" * 70)
    print(f"\nConnecting to {device['host']}...")

    try:
        # Establish SSH connection
        connection = ConnectHandler(**device)
        print("✓ SSH connection established")

        # Get device prompt (hostname)
        prompt = connection.find_prompt()
        print(f"✓ Device prompt: {prompt}")

        # Test commands
        commands = [
            'show memory summary',
            'show ip interface brief',
            'show interfaces GigabitEthernet0/0/0/0',
        ]

        for command in commands:
            print(f"\n{'=' * 70}")
            print(f"Command: {command}")
            print('=' * 70)

            output = connection.send_command(command)
            print(output)

        # Disconnect
        connection.disconnect()
        print("\n" + "=" * 70)
        print("✓ Test completed successfully")
        print("=" * 70)

        return 0

    except Exception as e:
        print(f"\n✗ Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
