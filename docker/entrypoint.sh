#!/bin/sh
# Container start: apply database migrations, then serve API + frontend.
# One uvicorn worker only — single-writer SQLite + in-process FAISS index
# (see CLAUDE.md). ECS runs exactly one task and stops the old task before
# starting a new one, so two processes never share data/ on EFS.
set -e

cd /app/backend
alembic upgrade head

cd /app
exec uvicorn app.serve:app --app-dir backend \
    --host 0.0.0.0 --port 8080 --workers 1 \
    --proxy-headers --forwarded-allow-ips '*'
