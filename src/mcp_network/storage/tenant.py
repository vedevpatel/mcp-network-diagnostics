"""Multi-tenant context management."""

from contextvars import ContextVar
from typing import Optional

# Thread-local tenant context
_tenant_context: ContextVar[str] = ContextVar("tenant_id", default="default")


def get_tenant_id() -> str:
    """Get current tenant ID from context.

    Returns:
        Current tenant ID (defaults to 'default')
    """
    return _tenant_context.get()


def set_tenant_id(tenant_id: str):
    """Set tenant ID in current context.

    Args:
        tenant_id: Tenant identifier
    """
    _tenant_context.set(tenant_id)


class TenantContext:
    """Context manager for tenant scoping.

    Usage:
        with TenantContext("customer-123"):
            # All database operations in this block
            # will be scoped to customer-123
            devices = device_repo.find_all()
    """

    def __init__(self, tenant_id: str):
        """Initialize tenant context.

        Args:
            tenant_id: Tenant identifier
        """
        self.tenant_id = tenant_id
        self.previous_tenant: Optional[str] = None

    def __enter__(self):
        """Enter tenant context."""
        self.previous_tenant = _tenant_context.get()
        _tenant_context.set(self.tenant_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit tenant context and restore previous."""
        if self.previous_tenant:
            _tenant_context.set(self.previous_tenant)
        else:
            _tenant_context.set("default")
