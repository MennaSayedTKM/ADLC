# syntax=docker/dockerfile:1
# ADLC — FastAPI backend + built React frontend in one image, served by one
# uvicorn process (backend/app/serve.py). Built and pushed to Docker Hub by
# .github/workflows/docker-publish.yml; runs on ECS Fargate (infra/), where
# data/ (SQLite DB, FAISS index, tiles, uploads) is an EFS volume at /app/data.

# ── Stage 1: build the frontend ──────────────────────────────────────────────
FROM node:22-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ── Stage 2: runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libgomp: OpenMP runtime used by faiss-cpu
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY config.py config.yaml ./
COPY ai/ ai/
COPY backend/ backend/
COPY --from=frontend /build/frontend/dist frontend/dist
COPY docker/entrypoint.sh /entrypoint.sh

# uid 1000 matches the EFS access point's owner (infra/adlc_stack.py)
RUN useradd --uid 1000 --create-home adlc \
    && mkdir -p /app/data \
    && chown adlc:adlc /app/data \
    && chmod 755 /entrypoint.sh
USER adlc

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
