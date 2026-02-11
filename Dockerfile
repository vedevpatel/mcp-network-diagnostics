# Multi-stage build for MCP Network Diagnostics
FROM python:3.10-slim as builder

# Install uv
RUN pip install uv

# Set working directory
WORKDIR /app

# Copy dependency files and source
COPY pyproject.toml ./
COPY README.md ./
COPY src/ ./src/

# Install package and dependencies
RUN uv pip install --system .

# Final stage
FROM python:3.10-slim

# Install runtime dependencies (ip = iproute2 for default gateway detection)
RUN apt-get update && apt-get install -y \
    iproute2 \
    iputils-ping \
    traceroute \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy from builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application
COPY src/ ./src/
COPY pyproject.toml README.md ./

# Create non-root user and data directory
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app

# Environment variables
ENV MCP_NETWORK_DATA_DIR=/data
ENV PYTHONUNBUFFERED=1
# Dashboard binds to 0.0.0.0 inside Docker (container networking)
ENV MCP_NETWORK_DASHBOARD_HOST=0.0.0.0

# Expose ports
EXPOSE 8080

# Switch to non-root user
USER appuser

# Health check: actually probe the dashboard HTTP endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/')" || exit 1

# Default command: run dashboard
CMD ["python", "-m", "mcp_network.dashboard"]
