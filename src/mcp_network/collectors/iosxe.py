"""
Cisco IOS-XE collector via SSH.

Connects to Cisco IOS-XE devices (IOSv, CSR1000v, Cat8000v) via SSH
and collects metrics by parsing CLI command output.
"""

import logging
import networkx as nx
from typing import Dict, Optional
from netmiko import ConnectHandler
from mcp_network.models.network import Device, Interface, Link
from mcp_network.parsers.iosxe import (
    parse_memory_summary,
    parse_cpu_usage,
    parse_interface_brief,
    parse_interface_detail,
)

logger = logging.getLogger(__name__)


class IOSXECollector:
    """
    Network collector that queries Cisco IOS-XE devices via SSH.
    """

    def __init__(
        self,
        topology_file: str,
        ssh_timeout: int = 30,
    ):
        """
        Initialize IOS-XE collector.

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
        """Establish SSH connection to a device."""
        try:
            connection = ConnectHandler(
                device_type='cisco_ios',  # IOS-XE uses cisco_ios
                host=device_config['host'],
                username=device_config['username'],
                password=device_config.get('password', ''),
                secret=device_config.get('secret', ''),
                port=device_config.get('port', 22),
                timeout=self.ssh_timeout,
                banner_timeout=60,
                session_timeout=60,
            )
            logger.debug(f"Connected to {device_config['id']} at {device_config['host']}")
            return connection
        except Exception as e:
            logger.error(f"Failed to connect to {device_config['id']}: {e}")
            return None

    def _query_device_metrics(self, connection: ConnectHandler) -> Dict:
        """Query all metrics from a device."""
        metrics = {
            "cpu_usage": 0.0,
            "memory_usage": 0.0,
            "interfaces": [],
        }

        try:
            # Get CPU usage
            cpu_output = connection.send_command("show processes cpu")
            metrics["cpu_usage"] = parse_cpu_usage(cpu_output)
            logger.debug(f"CPU usage: {metrics['cpu_usage']}%")

            # Get memory usage
            mem_output = connection.send_command("show processes memory sorted | include Processor")
            mem_data = parse_memory_summary(mem_output)
            metrics["memory_usage"] = mem_data.get("usage_percent", 0.0)
            logger.debug(f"Memory usage: {metrics['memory_usage']}%")

            # Get interface brief
            intf_output = connection.send_command("show ip interface brief")
            interfaces = parse_interface_brief(intf_output)

            # Get detailed stats for each interface
            for intf in interfaces:
                try:
                    detail_output = connection.send_command(
                        f"show interfaces {intf['name']}"
                    )
                    detail = parse_interface_detail(detail_output)
                    intf["utilization"] = detail.get("utilization_percent", 0.0)
                    intf["errors"] = detail.get("input_errors", 0) + detail.get("output_errors", 0)
                except Exception as e:
                    logger.warning(f"Failed to get details for {intf['name']}: {e}")
                    intf["utilization"] = 0.0
                    intf["errors"] = 0

            metrics["interfaces"] = interfaces

        except Exception as e:
            logger.error(f"Error querying device metrics: {e}")

        return metrics

    def _refresh_metrics(self):
        """Refresh metrics from all devices."""
        self.devices.clear()
        self.links.clear()
        self.graph.clear()

        # Query each device
        for device_config in self.topology.get('devices', []):
            device_id = device_config['id']
            logger.info(f"Querying device {device_id}...")

            connection = self._connect_device(device_config)
            if not connection:
                logger.warning(f"Skipping {device_id} - connection failed")
                continue

            try:
                metrics = self._query_device_metrics(connection)

                # Build Interface objects
                interfaces = []
                for intf_data in metrics.get("interfaces", []):
                    interface = Interface(
                        name=intf_data["name"],
                        utilization=intf_data.get("utilization", 0.0),
                        errors=intf_data.get("errors", 0),
                        status="up" if intf_data.get("protocol") == "up" else "down",
                    )
                    interfaces.append(interface)

                # Build Device object
                device = Device(
                    device_id=device_id,
                    device_type=device_config.get('type', 'router'),
                    cpu_usage=metrics.get("cpu_usage", 0.0),
                    memory_usage=metrics.get("memory_usage", 0.0),
                    interfaces=interfaces,
                )
                self.devices[device_id] = device
                self.graph.add_node(device_id)
                logger.info(f"Added device {device_id}: CPU={device.cpu_usage:.1f}%, "
                           f"Memory={device.memory_usage:.1f}%, "
                           f"Interfaces={len(interfaces)}")

            finally:
                connection.disconnect()

        # Build links from topology
        for link_config in self.topology.get('links', []):
            link = Link(
                src_device=link_config['src_device'],
                src_interface=link_config['src_interface'],
                dst_device=link_config['dst_device'],
                dst_interface=link_config['dst_interface'],
                latency_ms=link_config.get('default_latency_ms', 1.0),
            )
            self.links.append(link)

            # Add edge to graph
            self.graph.add_edge(
                link.src_device,
                link.dst_device,
                latency=link.latency_ms,
                src_interface=link.src_interface,
                dst_interface=link.dst_interface,
            )

        logger.info(f"Topology loaded: {len(self.devices)} devices, {len(self.links)} links")
