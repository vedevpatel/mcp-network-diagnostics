"""
Network path finding using NetworkX
"""

import networkx as nx
from typing import Optional


def find_path(graph: nx.Graph, source: str, target: str) -> list[str]:
    """
    Find the shortest path between source and target nodes in the graph.

    Args:
        graph (nx.Graph): The network graph.
        source (str): The source node.
        target (str): The target node.

    Returns:
        list[str]: List of device IDs representing the path from source to target.


    Raises:
        nx.NetworkXNoPath: If no path exists between source and target.
        nx.NodeNotFound: If either source or target node is not in the graph.
    """
    try:
        # use Dijkstra's w/ latency as weight
        path = nx.shortest_path(graph, source=source, target=target, weight="latency")
        return path
    except nx.NetworkXNoPath:
        raise ValueError(f"No path exists between {source} and {target}")
    except nx.NodeNotFound:
        raise ValueError(f"Device not found: '{target}'" if target not in graph else f"Device not found: '{source}'")
    

def get_path_details(graph: nx.Graph, path: list[str]) -> list[dict]:
    """
    Get detailed information about each hop in the path.
    
    Args:
        graph (nx.Graph): The network graph.
        path (list[str]): List of device IDs representing the path.
        
    Returns:
        list[dict]: List of dictionaries containing hop details.
    """
    hops = []

    for i in range(len(path) - 1):
        src_device = path[i]
        dst_device = path[i + 1]

        # get edge data (link info)
        edge_data = graph.get_edge_data(src_device, dst_device)
        if edge_data is None:
            continue  # skip if no edge data found

        hop = {
            "from_device": src_device,
            "to_device": dst_device,
            "from_interface": edge_data.get("src_interface"),
            "to_interface": edge_data.get("dst_interface"),
            "latency_ms": edge_data.get("latency", 0),
            "hop_number": i + 1
        }
        hops.append(hop)

    return hops


def calculate_total_latency(graph: nx.Graph, path: list[str]) -> float:
    """
    Calculate total latency for a given path.
    
    Args:
        graph: NetworkX graph of network topology
        path: List of device IDs in the path
    
    Returns:
        Total latency in milliseconds
    """
    total_latency = 0.0
    
    for i in range(len(path) - 1):
        src = path[i]
        dst = path[i + 1]
        edge_data = graph.get_edge_data(src, dst)
        total_latency += edge_data.get("latency", 0)
    
    return total_latency


def find_all_paths(graph: nx.Graph, src: str, dst: str, cutoff: Optional[int] = 5) -> list[list[str]]:
    """
    Find all simple paths between two devices (up to cutoff length).
    
    Args:
        graph: NetworkX graph of network topology
        src: Source device ID
        dst: Destination device ID
        cutoff: Maximum path length to search (default: 5 hops)
    
    Returns:
        List of paths, each path is a list of device IDs
    """
    try:
        paths = list(nx.all_simple_paths(graph, src, dst, cutoff=cutoff))
        return paths
    except nx.NetworkXNoPath:
        return []
    except nx.NodeNotFound:
        return []