FROM python:3.12-slim

WORKDIR /app

# System dependencies for voice (ffmpeg) + runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install dependencies with voice support
RUN pip install --no-cache-dir -e ".[voice]" && \
    pip install --no-cache-dir tortoise-orm[aiosqlite]

# Create data and model cache directories
RUN mkdir -p /app/data /cache/models

ENV DATABASE_URL=sqlite:///cache/models/krankenfahrt.db
ENV WHISPER_CACHE_DIR=/cache/models
ENV WHISPER_MODEL=small
ENV WHISPER_DEVICE=cpu
ENV HEALTH_PORT=${PORT:-8080}

CMD ["python3", "-m", "krankenfahrt.main"]
