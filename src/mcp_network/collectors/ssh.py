"""
Generic SSH collector for mixed Cisco platform topologies.

Reads device_type (iosxr | iosxe | nxos) per device in the topology
YAML and dispatches to the correct Netmiko device type, show commands,
and parsers automatically.
"""

import logging
import time
import networkx as nx
from typing import Dict, Optional
from netmiko import ConnectHandler
from mcp_network.models.network import Device, Interface, Link
from mcp_network.collectors.topology_loader import load_topology
from mcp_network.parsers import iosxr as iosxr_parsers
from mcp_network.parsers import iosxe as iosxe_parsers
from mcp_network.parsers import nxos as nxos_parsers

logger = logging.getLogger(__name__)

# Netmiko device_type strings per platform
NETMIKO_TYPES = {
    "iosxr": "cisco_xr",
    "iosxe": "cisco_ios",
    "nxos": "cisco_nxos",
}

# Show commands per platform.
# cpu=None means no separate CPU command (default 50.0).
# system_resources=<cmd> means one command returns both CPU and memory (NX-OS).
COMMANDS = {
    "iosxr": {
        "memory": "show memory summary",
        "cpu": None,
        "intf_brief": "show ip interface brief",
    },
    "iosxe": {
        "memory": "show processes memory sorted | include Processor",
        "cpu": "show processes cpu",
        "intf_brief": "show ip interface brief",
    },
    "nxos": {
        "system_resources": "show system resources",
        "memory": None,
        "cpu": None,
        "intf_brief": "show interface brief",
    },
}

# Parser functions per platform.
# system_resources=<fn> means one parser returns both cpu_percent and memory_percent.
PARSERS = {
    "iosxr": {
        "memory": iosxr_parsers.parse_memory_summary,
        "cpu": None,
        "intf_brief": iosxr_parsers.parse_interface_brief,
        "intf_detail": iosxr_parsers.parse_interface_detail,
    },
    "iosxe": {
        "memory": iosxe_parsers.parse_memory_summary,
        "cpu": iosxe_parsers.parse_cpu_usage,
        "intf_brief": iosxe_parsers.parse_interface_brief,
        "intf_detail": iosxe_parsers.parse_interface_detail,
    },
    "nxos": {
        "system_resources": nxos_parsers.parse_system_resources,
        "memory": None,
        "cpu": None,
        "intf_brief": nxos_parsers.parse_interface_brief,
        "intf_detail": nxos_parsers.parse_interface_detail,
    },
}


class SSHCollector:
    """
    Network collector that connects to Cisco devices via SSH.
    Supports mixed IOS-XR and IOS-XE devices in a single topology.
    """

    def __init__(
        self,
        topology_file: str,
        ssh_timeout: int = 30,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
    ):
        self.ssh_timeout = ssh_timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.topology = load_topology(topology_file)
        self.local_device: Optional[str] = self.topology.get("local_device")
        self.thresholds: dict = self.topology.get("thresholds", {})

        self.devices: Dict[str, Device] = {}
        self.links: list[Link] = []
        self.graph = nx.Graph()

        self._refresh_metrics()

    def _connect(self, device_config: dict) -> Optional[ConnectHandler]:
        """Open SSH connection using the platform-appropriate device type."""
        platform = device_config.get("device_type", "iosxr")
        netmiko_type = NETMIKO_TYPES.get(platform)
        if not netmiko_type:
            logger.error(f"Unknown device_type '{platform}' on {device_config['id']}")
            return None

        try:
            conn = ConnectHandler(
                device_type=netmiko_type,
                host=device_config["host"],
                username=device_config["username"],
                password=device_config.get("password", ""),
                secret=device_config.get("secret", ""),
                port=device_config.get("port", 22),
                timeout=self.ssh_timeout,
                banner_timeout=60,
                session_timeout=60,
            )
            logger.debug(f"Connected to {device_config['id']} at {device_config['host']}")
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to {device_config['id']}: {e}")
            return None

    def _collect_device_with_retry(self, device_config: dict) -> Optional[Device]:
        """Collect device data with retry logic and exponential backoff."""
        from mcp_network.collectors.health import get_health_tracker

        device_id = device_config["id"]
        health_tracker = get_health_tracker()

        for attempt in range(self.max_retries):
            try:
                device = self._collect_device(device_config)
                if device:
                    health_tracker.record_success(device_id)
                    return device
                else:
                    raise Exception("Collection returned None")
            except Exception as e:
                error_msg = str(e)
                logger.warning(
                    f"Collection attempt {attempt + 1}/{self.max_retries} failed for {device_id}: {error_msg}"
                )

                if attempt < self.max_retries - 1:
                    wait_time = self.backoff_factor ** attempt
                    logger.debug(f"Retrying {device_id} in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    # Final failure
                    logger.error(f"All {self.max_retries} attempts failed for {device_id}")
                    health_tracker.record_failure(device_id, error_msg)
                    return None

        return None

    def _collect_device(self, device_config: dict) -> Optional[Device]:
        """Connect, run show commands, parse output, return a Device."""
        device_id = device_config["id"]
        platform = device_config.get("device_type", "iosxr")
        cmds = COMMANDS.get(platform)
        parsers = PARSERS.get(platform)
        if not cmds or not parsers:
            logger.error(f"No command/parser config for platform '{platform}' on {device_id}")
            return None

        conn = self._connect(device_config)
        if not conn:
            return None

        try:
            # --- CPU + Memory ---
            cpu_usage = 50.0
            memory_usage = 0.0

            if cmds.get("system_resources") and parsers.get("system_resources"):
                # NX-OS: single command returns both CPU and memory
                sr_output = conn.send_command(cmds["system_resources"])
                sr_data = parsers["system_resources"](sr_output)
                cpu_usage = sr_data.get("cpu_percent", 50.0)
                memory_usage = sr_data.get("memory_percent", 0.0)
            else:
                # IOS-XR / IOS-XE: separate commands
                if cmds["cpu"] and parsers["cpu"]:
                    cpu_output = conn.send_command(cmds["cpu"])
                    cpu_usage = parsers["cpu"](cpu_output)

                if cmds["memory"] and parsers["memory"]:
                    mem_output = conn.send_command(cmds["memory"])
                    mem_data = parsers["memory"](mem_output)
                    # IOS-XR key: used_percent  |  IOS-XE key: usage_percent
                    memory_usage = mem_data.get("used_percent") or mem_data.get("usage_percent", 0.0)

            # --- Interfaces ---
            brief_output = conn.send_command(cmds["intf_brief"])
            brief_list = parsers["intf_brief"](brief_output)

            interfaces = []
            for intf in brief_list:
                utilization = 0.0
                errors = 0
                try:
                    detail_output = conn.send_command(f"show interfaces {intf['name']}")
                    detail = parsers["intf_detail"](detail_output)
                    utilization = detail.get("utilization_percent", 0.0)
                    errors = detail.get("input_errors", 0) + detail.get("output_errors", 0)
                except Exception as e:
                    logger.warning(f"Detail query failed for {intf['name']} on {device_id}: {e}")

                # Determine status: IOS-XR brief has 'status' field directly;
                # IOS-XE brief has 'protocol' field.  Both end up lowercased.
                raw_status = intf.get("protocol", intf.get("status", "down"))
                status = "up" if raw_status.lower() == "up" else "down"

                interfaces.append(Interface(
                    name=intf["name"],
                    utilization=utilization,
                    errors=errors,
                    status=status,
                ))

            return Device(
                device_id=device_id,
                device_type=device_config.get("type", "router"),
                cpu_usage=cpu_usage,
                memory_usage=memory_usage,
                interfaces=interfaces,
            )

        except Exception as e:
            logger.error(f"Error collecting metrics from {device_id}: {e}")
            return None
        finally:
            try:
                conn.disconnect()
            except Exception:
                pass

    def _refresh_metrics(self):
        """Poll every device and rebuild the graph.

        Supports partial collection: continues even if some devices fail.
        Failed devices are tracked in health monitoring system.
        """
        self.devices.clear()
        self.links.clear()
        self.graph.clear()

        successful_devices = 0
        failed_devices = 0

        for device_config in self.topology.get("devices", []):
            device = self._collect_device_with_retry(device_config)
            if device:
                self.devices[device.device_id] = device
                self.graph.add_node(device.device_id)
                successful_devices += 1
                logger.info(
                    f"{device.device_id}: CPU={device.cpu_usage:.1f}% "
                    f"Mem={device.memory_usage:.1f}% Intf={len(device.interfaces)}"
                )
            else:
                failed_devices += 1
                logger.warning(f"Skipping {device_config['id']} — collection failed after {self.max_retries} retries")

        for link_config in self.topology.get("links", []):
            link = Link(
                src_device=link_config["src_device"],
                src_interface=link_config["src_interface"],
                dst_device=link_config["dst_device"],
                dst_interface=link_config["dst_interface"],
                latency_ms=link_config.get("default_latency_ms", 1.0),
            )
            self.links.append(link)
            self.graph.add_edge(
                link.src_device,
                link.dst_device,
                latency=link.latency_ms,
                src_interface=link.src_interface,
                dst_interface=link.dst_interface,
            )

        logger.info(
            f"SSH collector ready: {successful_devices} devices collected, "
            f"{failed_devices} failed, {len(self.links)} links"
        )

    def _device_config(self, device_id: str) -> Optional[dict]:
        """Look up raw topology config for a device by ID."""
        for cfg in self.topology.get("devices", []):
            if cfg["id"] == device_id:
                return cfg
        return None

    def collect_configs(self) -> None:
        """Collect and track configuration snapshots for all devices.

        Called periodically to track config changes over time.
        Failures are logged but do not stop collection.
        """
        from mcp_network.config import get_config_tracker

        config_tracker = get_config_tracker()
        successful = 0
        failed = 0

        for device_id in self.devices:
            try:
                config_text = self.run_command(device_id, "show running-config")
                config_tracker.add_snapshot(device_id, config_text)
                successful += 1
                logger.debug(f"Collected config snapshot for {device_id}")
            except Exception as e:
                failed += 1
                logger.warning(f"Failed to collect config for {device_id}: {e}")

        logger.info(f"Config collection complete: {successful} successful, {failed} failed")

    def run_command(self, device_id: str, command: str) -> str:
        """
        Open a fresh SSH session to device_id, run command, return output.

        Raises ValueError if the device is unknown, not reachable,
        or the command fails safety validation.
        """
        import re

        # Defense-in-depth: reject control chars even if the tool layer missed them
        if any(c in command for c in '\n\r\x00'):
            raise ValueError("Command contains forbidden control characters")

        # Must start with a read-only keyword
        if not re.match(r'^(show|display|ping|traceroute)\s+', command, re.IGNORECASE):
            raise ValueError("Only read-only commands are permitted at the collector level")

        cfg = self._device_config(device_id)
        if not cfg:
            raise ValueError(f"Device '{device_id}' not found in topology")

        conn = self._connect(cfg)
        if not conn:
            raise ValueError(f"SSH connection to '{device_id}' failed")

        try:
            return conn.send_command(command)
        finally:
            try:
                conn.disconnect()
            except Exception:
                pass
