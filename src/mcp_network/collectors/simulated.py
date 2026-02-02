"""Simulated network topology generator for testing."""
import random
import networkx as nx
from mcp_network.models.network import Device, Interface, Link


class SimulatedCollector:
    """Generate a fake but realistic network topology."""
    
    def __init__(self):
        """Initialize the simulated network."""
        self.devices: dict[str, Device] = {}
        self.links: list[Link] = []
        self.graph: nx.Graph = nx.Graph()
        self._generate_topology()
        self._build_graph()
    
    def _generate_topology(self):
        """Create a mesh of routers with realistic metrics."""
        # Create 10 routers in a mesh topology
        for i in range(1, 11):
            device_id = f"R{i}"
            
            # Some devices are congested, others are healthy
            cpu_congested = i % 3 == 0  # Every 3rd device
            interface_congested = i % 4 == 0  # Every 4th device
            
            interfaces = []
            for j in range(4):  # 4 interfaces per router
                interface = Interface(
                    name=f"Gi0/{j}",
                    utilization=random.uniform(80, 98) if interface_congested else random.uniform(5, 60),
                    errors=random.randint(500, 2000) if interface_congested else random.randint(0, 50),
                    status="up"
                )
                interfaces.append(interface)
            
            device = Device(
                device_id=device_id,
                device_type="router",
                cpu_usage=random.uniform(85, 98) if cpu_congested else random.uniform(10, 70),
                memory_usage=random.uniform(40, 85),
                interfaces=interfaces
            )
            
            self.devices[device_id] = device
        
        # Create links in a partial mesh (not fully connected)
        # Each router connects to 2-3 other routers
        connections = [
            ("R1", "Gi0/0", "R2", "Gi0/0", 2.1),
            ("R1", "Gi0/1", "R3", "Gi0/0", 1.8),
            ("R2", "Gi0/1", "R3", "Gi0/1", 2.5),
            ("R2", "Gi0/2", "R4", "Gi0/0", 3.2),
            ("R3", "Gi0/2", "R5", "Gi0/0", 1.9),
            ("R4", "Gi0/1", "R5", "Gi0/1", 2.8),
            ("R4", "Gi0/2", "R6", "Gi0/0", 2.3),
            ("R5", "Gi0/2", "R7", "Gi0/0", 1.7),
            ("R6", "Gi0/1", "R7", "Gi0/1", 2.9),
            ("R6", "Gi0/2", "R8", "Gi0/0", 2.1),
            ("R7", "Gi0/2", "R9", "Gi0/0", 3.1),
            ("R8", "Gi0/1", "R9", "Gi0/1", 1.6),
            ("R8", "Gi0/2", "R10", "Gi0/0", 2.4),
            ("R9", "Gi0/2", "R10", "Gi0/1", 2.7),
            ("R1", "Gi0/2", "R4", "Gi0/3", 4.5),  # Longer path option
            ("R3", "Gi0/3", "R7", "Gi0/3", 5.2),  # Another alternate path
        ]
        
        for src_dev, src_int, dst_dev, dst_int, latency in connections:
            link = Link(
                src_device=src_dev,
                src_interface=src_int,
                dst_device=dst_dev,
                dst_interface=dst_int,
                latency_ms=latency
            )
            self.links.append(link)
    
    def _build_graph(self):
        """Build NetworkX graph from devices and links."""
        # Add all devices as nodes
        for device_id in self.devices:
            self.graph.add_node(device_id)
        
        # Add links as edges (undirected graph)
        for link in self.links:
            self.graph.add_edge(
                link.src_device,
                link.dst_device,
                latency=link.latency_ms,
                src_interface=link.src_interface,
                dst_interface=link.dst_interface
            )


# Singleton instance
_collector = None


def get_network() -> SimulatedCollector:
    """Get the singleton simulated network instance."""
    global _collector
    if _collector is None:
        _collector = SimulatedCollector()
    return _collector
