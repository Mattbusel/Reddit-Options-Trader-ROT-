FROM python:3.12-slim

# Prevent Python from buffering stdout/stderr (important for Railway logs)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip first
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy ONLY pyproject.toml first for dependency caching.
# This layer is cached until pyproject.toml changes, so deps
# don't recompile on every code change.
COPY pyproject.toml ./

# Install dependencies separately (without the project itself).
# This is the heavy step — cached by Docker unless deps change.
RUN pip install --no-cache-dir \
    praw \
    "yfinance" \
    "feedparser>=6.0" \
    "pydantic>=2.0" \
    "pydantic-settings>=2.0" \
    "openai>=1.0" \
    "anthropic>=0.20" \
    "fastapi>=0.109" \
    "uvicorn[standard]>=0.27" \
    "aiosqlite>=0.19" \
    "python-jose[cryptography]>=3.3" \
    "bcrypt>=4.0" \
    "httpx>=0.26" \
    "jinja2>=3.1" \
    "python-multipart>=0.0.6" \
    "stripe>=7.0"

# NOW copy source code (changes frequently, but deps are already cached)
COPY src/ ./src/

# Install the project itself (fast — just sets up the package, deps already installed)
RUN pip install --no-cache-dir --no-deps .

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
