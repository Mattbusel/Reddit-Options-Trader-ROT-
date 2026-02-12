# ── Stage 1: Build dependencies ──
FROM python:3.12-slim AS builder

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
    "stripe>=7.0"

COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .

# ── Stage 2: Lean runtime image (no gcc, no build tools) ──
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy the virtual env with all installed packages
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Create data directory for SQLite
RUN mkdir -p /app/data

# Default env vars (Railway overrides these)
ENV ROT_STORAGE_ROOT=/app/data
ENV ROT_WEB_HOST=0.0.0.0
ENV PORT=8000

EXPOSE ${PORT}

CMD python -m rot.app.server
