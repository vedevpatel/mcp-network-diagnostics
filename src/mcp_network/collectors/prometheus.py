"""Prometheus-based network collector."""
import logging
import networkx as nx
import yaml
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from prometheus_api_client import PrometheusConnect
from mcp_network.models.network import Device, Interface, Link

logger = logging.getLogger(__name__)


class MetricCache:
    """Simple time-based cache for Prometheus metrics."""

    def __init__(self, ttl_seconds: int = 30):
        self._cache: Dict[str, tuple[Any, datetime]] = {}
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            value, timestamp = self._cache[key]
            if datetime.now() - timestamp < self._ttl:
                return value
        return None

    def set(self, key: str, value: Any):
        self._cache[key] = (value, datetime.now())

    def clear(self):
        self._cache.clear()


class PrometheusCollector:
    """Network collector that queries Prometheus for real metrics."""

    def __init__(
        self,
        prometheus_url: str,
        topology_file: str,
        cache_ttl: int = 30
    ):
        """
        Initialize Prometheus collector.

        Args:
            prometheus_url: URL of Prometheus server (e.g., http://localhost:9090)
            topology_file: Path to YAML topology configuration
            cache_ttl: Metric cache TTL in seconds
        """
        self.prometheus_url = prometheus_url
        self.topology_file = topology_file
        self._cache = MetricCache(ttl_seconds=cache_ttl)

        # Initialize Prometheus client
        try:
            self.client = PrometheusConnect(url=prometheus_url, disable_ssl=True)
            logger.info(f"Connected to Prometheus at {prometheus_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Prometheus: {e}")
            raise

        # Load topology configuration
        self.topology = self._load_topology(topology_file)

        # Initialize data structures
        self.devices: Dict[str, Device] = {}
        self.links: list[Link] = []
        self.graph = nx.Graph()

        # Populate metrics
        self._refresh_metrics()

    def _load_topology(self, topology_file: str) -> dict:
        """Load network topology from YAML configuration."""
        try:
            with open(topology_file, 'r') as f:
                topology = yaml.safe_load(f)
            logger.info(f"Loaded topology: {len(topology['devices'])} devices, {len(topology['links'])} links")
            return topology
        except FileNotFoundError:
            logger.error(f"Topology file not found: {topology_file}")
            raise
        except yaml.YAMLError as e:
            logger.error(f"Invalid YAML in topology file: {e}")
            raise

    def _query_metric(
        self,
        query: str,
        cache_key: str,
        default: float = 0.0
    ) -> float:
        """
        Query Prometheus with caching and fallback.

        Args:
            query: PromQL query string
            cache_key: Unique key for caching
            default: Default value if query fails

        Returns:
            Metric value or default
        """
        # Check cache first
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        # Query Prometheus
        try:
            result = self.client.custom_query(query)
            if result and len(result) > 0:
                value = float(result[0]['value'][1])
                self._cache.set(cache_key, value)
                return value
        except Exception as e:
            logger.warning(f"Prometheus query failed: {e}, using default: {default}")

        return default

    def _query_cpu_usage(self, instance: str) -> float:
        """Query CPU usage for a device instance."""
        query = f'100 - (avg by (instance) (rate(node_cpu_seconds_total{{mode="idle", instance="{instance}"}}[5m])) * 100)'
        return self._query_metric(query, f"cpu_{instance}", default=50.0)

    def _query_memory_usage(self, instance: str) -> float:
        """Query memory usage for a device instance."""
        query = f'100 - ((node_memory_MemAvailable_bytes{{instance="{instance}"}} / node_memory_MemTotal_bytes{{instance="{instance}"}}) * 100)'
        return self._query_metric(query, f"memory_{instance}", default=60.0)

    def _query_interface_utilization(
        self,
        instance: str,
        interface: str,
        link_speed_mbps: int
    ) -> float:
        """Query interface utilization percentage."""
        link_speed_bits = link_speed_mbps * 1_000_000  # Mbps to bps
        query = f'''
        (
          rate(node_network_receive_bytes_total{{instance="{instance}", device="{interface}"}}[5m]) +
          rate(node_network_transmit_bytes_total{{instance="{instance}", device="{interface}"}}[5m])
        ) * 8 / {link_speed_bits} * 100
        '''
        return self._query_metric(query, f"util_{instance}_{interface}", default=30.0)

    def _query_interface_errors(self, instance: str, interface: str) -> int:
        """Query interface error count."""
        query = f'''
        rate(node_network_receive_errs_total{{instance="{instance}", device="{interface}"}}[5m]) +
        rate(node_network_transmit_errs_total{{instance="{instance}", device="{interface}"}}[5m])
        '''
        return int(self._query_metric(query, f"errors_{instance}_{interface}", default=0.0))

    def _query_interface_status(self, instance: str, interface: str) -> str:
        """Query interface operational status."""
        query = f'node_network_up{{instance="{instance}", device="{interface}"}}'
        status_value = self._query_metric(query, f"status_{instance}_{interface}", default=1.0)
        return "up" if status_value == 1.0 else "down"

    def _build_device(self, device_config: dict) -> Device:
        """Build Device object from config and Prometheus metrics."""
        device_id = device_config['id']
        instance = device_config['prometheus_labels']['instance']

        # Query device-level metrics
        cpu_usage = self._query_cpu_usage(instance)
        memory_usage = self._query_memory_usage(instance)

        # Build interfaces
        interfaces = []
        for iface_config in device_config['interfaces']:
            interface = Interface(
                name=iface_config['name'],
                utilization=self._query_interface_utilization(
                    instance,
                    iface_config['prometheus_name'],
                    iface_config['link_speed_mbps']
                ),
                errors=self._query_interface_errors(
                    instance,
                    iface_config['prometheus_name']
                ),
                status=self._query_interface_status(
                    instance,
                    iface_config['prometheus_name']
                )
            )
            interfaces.append(interface)

        return Device(
            device_id=device_id,
            device_type=device_config['type'],
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
            interfaces=interfaces
        )

    def _build_link(self, link_config: dict) -> Link:
        """Build Link object from config."""
        return Link(
            src_device=link_config['src_device'],
            src_interface=link_config['src_interface'],
            dst_device=link_config['dst_device'],
            dst_interface=link_config['dst_interface'],
            latency_ms=link_config.get('default_latency_ms', 2.0)
        )

    def _refresh_metrics(self):
        """Query Prometheus and populate devices, links, and graph."""
        # Clear previous state
        self.devices = {}
        self.links = []
        self.graph = nx.Graph()

        # Build devices from topology config
        for device_config in self.topology['devices']:
            device = self._build_device(device_config)
            self.devices[device.device_id] = device
            self.graph.add_node(device.device_id)

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
