FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy project files first (needed for pip install)
COPY pyproject.toml .
COPY src/ src/

# Install dependencies
RUN pip install --no-cache-dir -e ".[dev]" && \
    pip install --no-cache-dir tortoise-orm[aiosqlite]

# Create data directory
RUN mkdir -p /app/data
ENV DATABASE_URL=sqlite:///app/data/krankenfahrt.db

# Health server port
ENV HEALTH_PORT=${PORT:-8080}

CMD ["python", "-m", "krankenfahrt.main"]
