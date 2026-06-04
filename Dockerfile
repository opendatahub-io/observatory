# ---- Stage 1: Build frontend ----
FROM node:20-alpine AS frontend-build

WORKDIR /build

COPY src/frontend/package.json src/frontend/package-lock.json* ./
RUN npm ci

COPY src/frontend/ ./
RUN npm run build


# ---- Stage 2: Production runtime ----
FROM python:3.11-slim AS runtime

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install curl for the health check
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (pyproject.toml + src/backend package)
COPY pyproject.toml ./
COPY src/backend/ src/backend/
RUN pip install --no-cache-dir .

# Copy built frontend assets from stage 1
COPY --from=frontend-build /build/dist/ src/frontend/dist/

# Copy seed data and alembic config
COPY data/seed.json data/seed.json
COPY org-pulse-config.json ./
COPY alembic.ini ./
COPY src/alembic/ src/alembic/

# Create non-root user and data directory
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid 1000 --no-create-home appuser \
    && mkdir -p /data \
    && chown appuser:appuser /data

# Environment
ENV OBSERVATORY_DATABASE_PATH=/data/observatory.db \
    OBSERVATORY_STATIC_DIR=/app/src/frontend/dist

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

USER 1000

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
