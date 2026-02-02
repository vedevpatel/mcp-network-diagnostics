"""
Network entity models using Pydantic.
"""

from typing import Optional
from pydantic import BaseModel, Field


class Interface(BaseModel):
    """
    Network interface on a device.
    """
    
    name: str = Field(description="Interface name (e.g., 'Gi0/1')")
    utilization: float = Field(ge=0, le=100, description="Utilization percentage")
    errors: int = Field(ge=0, description="Error count")
    status: str = Field(pattern="^(up|down)$", description="Interface status")
    
    class Config:
        json_schema_extra = {
            "example": {
                "name": "Gi0/1",
                "utilization": 45.2,
                "errors": 12,
                "status": "up"
            }
        }


class Device(BaseModel):
    """
    Network device (router, switch, firewall).
    """
    
    device_id: str = Field(description="Unique device identifier")
    device_type: str = Field(description="Device type (router, switch, firewall)")
    cpu_usage: float = Field(ge=0, le=100, description="CPU utilization percentage")
    memory_usage: float = Field(ge=0, le=100, description="Memory utilization percentage")
    interfaces: list[Interface] = Field(default_factory=list, description="Network interfaces")
    
    class Config:
        json_schema_extra = {
            "example": {
                "device_id": "R1",
                "device_type": "router",
                "cpu_usage": 65.5,
                "memory_usage": 42.1,
                "interfaces": []
            }
        }


class Link(BaseModel):
    """
    Connection between two devices.
    """
    
    src_device: str = Field(description="Source device ID")
    src_interface: str = Field(description="Source interface name")
    dst_device: str = Field(description="Destination device ID")
    dst_interface: str = Field(description="Destination interface name")
    latency_ms: Optional[float] = Field(None, ge=0, description="Link latency in milliseconds")
    
    class Config:
        json_schema_extra = {
            "example": {
                "src_device": "R1",
                "src_interface": "Gi0/1",
                "dst_device": "R2",
                "dst_interface": "Gi0/0",
                "latency_ms": 2.5
            }
        }
