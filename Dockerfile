# ── Stage 1: Build dependencies ──
FROM python:3.14-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip setuptools wheel

COPY pyproject.toml /build/
WORKDIR /build

# Install all deps into a virtual env so we can copy it cleanly
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

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
    "stripe>=7.0" \
    "scikit-learn>=1.3" \
    "numpy>=1.24" \
    "psutil>=5.9"

COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .

# ── Stage 2: Lean runtime image (no gcc, no build tools) ──
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy the virtual env with all installed packages
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# gosu for dropping privileges in entrypoint + non-root user
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 rot \
    && useradd --uid 1000 --gid rot --shell /bin/false rot

# Create data directory for SQLite (owned by non-root user)
RUN mkdir -p /app/data && chown rot:rot /app/data

# Entrypoint: fix ownership of volume-mounted data dir then drop to non-root
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Default env vars (Railway overrides these)
ENV ROT_STORAGE_ROOT=/app/data
ENV ROT_WEB_HOST=0.0.0.0
ENV PORT=8000

EXPOSE ${PORT}

# Start as root so entrypoint can chown the volume, then exec as rot
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "rot.app.server"]
