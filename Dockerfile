# Multi-stage Dockerfile for Blind Debate Adjudicator v3
# Stage 1: Build dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim AS runtime

WORKDIR /app

# Create non-root user
RUN groupadd -r debate && useradd -r -g debate debate

# Copy installed packages from builder
COPY --from=builder /root/.local /home/debate/.local
ENV PATH=/home/debate/.local/bin:$PATH

# Copy application code
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY skills/ ./skills/
COPY scripts/ ./scripts/
COPY data/ ./data/
COPY tests/ ./tests/ 2>/dev/null || true
COPY acceptance/ ./acceptance/ 2>/dev/null || true

# Create data directory and set permissions
RUN mkdir -p /app/data && chown -R debate:debate /app

USER debate

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/health')" || exit 1

# Run the application
CMD ["python", "-m", "backend.app_v3"]
