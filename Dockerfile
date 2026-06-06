# Stage 1: Builder — compiles deps (faster-whisper has CTranslate2 native code)
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create venv for clean dependency isolation
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml ./
COPY src/ src/

# Install full app + voice extras (faster-whisper, CTranslate2 compile happens here)
RUN pip install --no-cache-dir ".[voice]"


# Stage 2: Runtime — slim, no build tools
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd --create-home --shell /bin/bash krankenfahrt

# Copy venv from builder (all compiled deps)
COPY --from=builder /opt/venv /opt/venv

# Copy application source
COPY src/ /app/src/
COPY pyproject.toml /app/

# Data directory for SQLite
RUN mkdir -p /app/data && \
    chown -R krankenfahrt:krankenfahrt /app /opt/venv

USER krankenfahrt

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src

# Health check — uses the built-in health server (stdlib, port from $PORT env)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8080}/health')" || exit 1

EXPOSE 8080

WORKDIR /app
CMD ["python", "-m", "krankenfahrt.main"]
