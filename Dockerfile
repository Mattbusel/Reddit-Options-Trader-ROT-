FROM python:3.12-slim

# Prevent Python from buffering stdout/stderr (important for Railway logs)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first (Docker layer caching)
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# Copy application code
COPY src/ ./src/

# Create data directory for SQLite
RUN mkdir -p /app/data

# Default env vars (Railway overrides these)
ENV ROT_STORAGE_ROOT=/app/data
ENV ROT_WEB_HOST=0.0.0.0
ENV PORT=8000

# Railway sets PORT dynamically; use it
EXPOSE ${PORT}

# Start the server
CMD python -m rot.app.server
