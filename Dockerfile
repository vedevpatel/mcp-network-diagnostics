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

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
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

# Create data directory
RUN mkdir -p /data

# Environment variables
ENV MCP_NETWORK_DATA_DIR=/data
ENV PYTHONUNBUFFERED=1

# Expose ports
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Default command: run dashboard
CMD ["python", "-m", "mcp_network.dashboard"]
