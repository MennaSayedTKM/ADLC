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

# Debian security updates for the base image's own packages (the ECR scan
# flags e.g. zlib/perl CVEs in python:3.12-slim until the base is rebuilt),
# plus libgomp: OpenMP runtime used by faiss-cpu, and a headless JRE +
# Graphviz + fonts for PlantUML (use-case diagrams in the business requirements
# PDF / Confluence page; rendered locally, never by an outside service).
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libgomp1 default-jre-headless graphviz fonts-dejavu-core curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# PlantUML (MIT-licensed build), pinned and checksum-verified. Path matches
# plantuml_jar in config.yaml.
ARG PLANTUML_VERSION=1.2026.8
ARG PLANTUML_SHA256=3629c9cd017c7f73e6450396eea0040216c7e1eef8473ce33cc1aad469dab2f9
RUN mkdir -p /app/tools \
    && curl -fsSL -o /app/tools/plantuml.jar \
        "https://github.com/plantuml/plantuml/releases/download/v${PLANTUML_VERSION}/plantuml-mit-${PLANTUML_VERSION}.jar" \
    && echo "${PLANTUML_SHA256}  /app/tools/plantuml.jar" | sha256sum -c -

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
