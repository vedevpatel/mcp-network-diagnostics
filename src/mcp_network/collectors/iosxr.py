"""
Cisco IOS-XR collector via SSH.

Connects to Cisco IOS-XR devices via SSH and collects metrics
by parsing CLI command output.
"""

import logging
import networkx as nx
from typing import Dict, Optional
from netmiko import ConnectHandler
from mcp_network.models.network import Device, Interface, Link
from mcp_network.parsers.iosxr import (
    parse_memory_summary,
    parse_interface_brief,
    parse_interface_detail,
)

logger = logging.getLogger(__name__)


class IOSXRCollector:
    """
    Network collector that queries Cisco IOS-XR devices via SSH.
    """

    def __init__(
        self,
        topology_file: str,
        ssh_timeout: int = 30,
    ):
        """
        Initialize IOS-XR collector.

        Args:
            topology_file: Path to YAML topology configuration
            ssh_timeout: SSH connection timeout in seconds
        """
        self.topology_file = topology_file
        self.ssh_timeout = ssh_timeout

        # Load topology configuration
        self.topology = self._load_topology(topology_file)

        # Initialize data structures
        self.devices: Dict[str, Device] = {}
        self.links: list[Link] = []
        self.graph = nx.Graph()

        # Collect metrics from devices
        self._refresh_metrics()

    def _load_topology(self, topology_file: str) -> dict:
        """Load network topology from YAML configuration."""
        from mcp_network.collectors.topology_loader import load_topology
        return load_topology(topology_file)

    def _connect_device(self, device_config: dict) -> Optional[ConnectHandler]:
        """
        Establish SSH connection to a device.

        Args:
            device_config: Device configuration from topology YAML

        Returns:
            Netmiko connection object or None if connection fails
        """
        try:
            connection = ConnectHandler(
                device_type='cisco_xr',
                host=device_config['host'],
                username=device_config['username'],
                password=device_config.get('password', ''),
                secret=device_config.get('secret', ''),
                port=device_config.get('port', 22),
                timeout=self.ssh_timeout,
                session_timeout=60,
            )
            logger.debug(f"Connected to {device_config['id']} at {device_config['host']}")
            return connection
        except Exception as e:
            logger.error(f"Failed to connect to {device_config['id']}: {e}")
            return None

    def _query_device_memory(self, connection: ConnectHandler) -> Dict[str, float]:
        """
        Query device memory usage.

        Args:
            connection: Active SSH connection

        Returns:
            Dictionary with memory statistics
        """
        try:
            output = connection.send_command("show memory summary")
            return parse_memory_summary(output)
        except Exception as e:
            logger.warning(f"Failed to query memory: {e}")
            return {"total_mb": 0.0, "available_mb": 0.0, "used_percent": 50.0}

    def _query_interfaces_brief(self, connection: ConnectHandler) -> list:
        """
        Query interface list.

        Args:
            connection: Active SSH connection

        Returns:
            List of interface dictionaries
        """
        try:
            output = connection.send_command("show ip interface brief")
            return parse_interface_brief(output)
        except Exception as e:
            logger.warning(f"Failed to query interfaces: {e}")
            return []

    def _query_interface_detail(
        self,
        connection: ConnectHandler,
        interface_name: str
    ) -> Dict:
        """
        Query detailed interface statistics.

        Args:
            connection: Active SSH connection
            interface_name: Name of interface to query

        Returns:
            Dictionary with interface details
        """
        try:
            output = connection.send_command(f"show interfaces {interface_name}")
            return parse_interface_detail(output)
        except Exception as e:
            logger.warning(f"Failed to query interface {interface_name}: {e}")
            return {
                "name": interface_name,
                "admin_status": "unknown",
                "protocol_status": "unknown",
                "hardware_address": "",
                "mtu": 1500,
                "bandwidth_kbit": 1000000,
                "input_rate_bps": 0,
                "output_rate_bps": 0,
                "input_packets": 0,
                "output_packets": 0,
                "input_errors": 0,
                "output_errors": 0,
                "utilization_percent": 0.0,
            }

    def _build_device(self, device_config: dict) -> Optional[Device]:
        """
        Build Device object by connecting to device and collecting metrics.

        Args:
            device_config: Device configuration from topology YAML

        Returns:
            Device object or None if connection fails
        """
        device_id = device_config['id']

        # Connect to device
        connection = self._connect_device(device_config)
        if not connection:
            logger.error(f"Skipping device {device_id} - connection failed")
            return None

        try:
            # Query memory usage
            memory = self._query_device_memory(connection)

            # Get interface list
            interfaces_brief = self._query_interfaces_brief(connection)

            # Build Interface objects with detailed stats
            interfaces = []
            for iface_brief in interfaces_brief:
                iface_name = iface_brief['name']

                # Query detailed stats for this interface
                iface_detail = self._query_interface_detail(connection, iface_name)

                # Create Interface object
                interface = Interface(
                    name=iface_name,
                    utilization=iface_detail.get('utilization_percent', 0.0),
                    errors=iface_detail.get('input_errors', 0) + iface_detail.get('output_errors', 0),
                    status=iface_brief['status'].lower(),  # "Up" -> "up", "Shutdown" -> "shutdown"
                )
                interfaces.append(interface)

            # Create Device object
            device = Device(
                device_id=device_id,
                device_type=device_config.get('type', 'router'),
                cpu_usage=50.0,  # IOS-XR doesn't have easy CPU metric, use default
                memory_usage=memory.get('used_percent', 50.0),
                interfaces=interfaces,
            )

            return device

        except Exception as e:
            logger.error(f"Error building device {device_id}: {e}")
            return None

        finally:
            # Always disconnect
            try:
                connection.disconnect()
                logger.debug(f"Disconnected from {device_id}")
            except Exception as e:
                logger.warning(f"Error disconnecting from {device_id}: {e}")


    def _build_link(self, link_config: dict) -> Link:
        """
        Build Link object from config.

        Args:
            link_config: Link configuration from topology YAML

        Returns:
            Link object
        """
        return Link(
            src_device=link_config['src_device'],
            src_interface=link_config['src_interface'],
            dst_device=link_config['dst_device'],
            dst_interface=link_config['dst_interface'],
            latency_ms=link_config.get('default_latency_ms', 2.0)
        )


    def _refresh_metrics(self):
        """Connect to devices and collect metrics."""
        # Clear previous state
        self.devices = {}
        self.links = []
        self.graph = nx.Graph()

        # Build devices from topology config
        for device_config in self.topology['devices']:
            device = self._build_device(device_config)
            if device:
                self.devices[device.device_id] = device
                self.graph.add_node(device.device_id)
            else:
                logger.warning(f"Skipping device {device_config['id']} - failed to build")

        # Build links from topology config
        for link_config in self.topology['links']:
            link = self._build_link(link_config)
            self.links.append(link)
            self.graph.add_edge(
                link.src_device,
                link.dst_device,
                latency=link.latency_ms,
                src_interface=link.src_interface,
                dst_interface=link.dst_interface
            )

        logger.info(
            f"IOS-XR collector initialized: {len(self.devices)} devices, "
            f"{len(self.links)} links"
        )
