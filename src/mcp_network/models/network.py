"""Network data models using Pydantic for validation."""
from pydantic import BaseModel
import networkx as nx


class Interface(BaseModel):
    """Network interface with utilization and error metrics."""
    name: str
    utilization: float  # Percentage 0-100
    errors: int
    status: str  # "up" or "down"


class Device(BaseModel):
    """Network device (router/switch) with health metrics."""
    device_id: str
    device_type: str  # "router" or "switch"
    cpu_usage: float  # Percentage 0-100
    memory_usage: float  # Percentage 0-100
    interfaces: list[Interface]


class Link(BaseModel):
    """Connection between two devices."""
    src_device: str  # Source Device ID
    src_interface: str  # Source interface name
    dst_device: str  # Destination Device ID
    dst_interface: str  # Destination interface name
    latency_ms: float


class NetworkState(BaseModel):
    """Complete network state snapshot."""
    devices: dict[str, Device]
    links: list[Link]
    graph: nx.Graph

    class Config:
        arbitrary_types_allowed = True  # Allow networkx Graph type
