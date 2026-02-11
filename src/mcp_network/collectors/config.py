"""Collector configuration and factory."""
import logging

logger = logging.getLogger(__name__)

_collector_instance = None
_collector_type = "simulated"
_collector_config = {}


def configure_collector(collector_type: str = "simulated", **config):
    """Configure which collector to use globally."""
    global _collector_type, _collector_config
    _collector_type = collector_type
    _collector_config = config
    logger.info(f"Configured collector: {collector_type}")


def get_network():
    """Get the configured network collector singleton."""
    global _collector_instance

    if _collector_instance is None:

        if _collector_type == "simulated":
            from mcp_network.collectors.simulated import SimulatedCollector
            _collector_instance = SimulatedCollector()

        elif _collector_type == "prometheus":
            from mcp_network.collectors.prometheus import PrometheusCollector
            _collector_instance = PrometheusCollector(
                prometheus_url=_collector_config.get("prometheus_url"),
                topology_file=_collector_config.get("topology_file"),
                cache_ttl=_collector_config.get("cache_ttl", 30)
            )

        elif _collector_type == "iosxr":
            from mcp_network.collectors.iosxr import IOSXRCollector
            _collector_instance = IOSXRCollector(
                topology_file=_collector_config.get("topology_file"),
                ssh_timeout=_collector_config.get("ssh_timeout", 30)
            )

        elif _collector_type == "iosxe":
            from mcp_network.collectors.iosxe import IOSXECollector
            _collector_instance = IOSXECollector(
                topology_file=_collector_config.get("topology_file"),
                ssh_timeout=_collector_config.get("ssh_timeout", 30)
            )

        elif _collector_type == "ssh":
            from mcp_network.collectors.ssh import SSHCollector
            _collector_instance = SSHCollector(
                topology_file=_collector_config.get("topology_file"),
                ssh_timeout=_collector_config.get("ssh_timeout", 30)
            )

        else:
            raise ValueError(f"Unknown collector type: {_collector_type}")

    return _collector_instance
