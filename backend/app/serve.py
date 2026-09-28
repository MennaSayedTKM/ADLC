"""
serve.py
Production entry point for the container: one process serving both the
API and the built frontend, so the image needs no nginx.

    /api/*  -> the FastAPI app from main.py, prefix stripped — the same
               contract as the Vite dev proxy (frontend/vite.config.ts), so
               frontend/src/api/client.ts works unchanged
    /*      -> frontend/dist (index.html + assets)

Local development keeps using `uvicorn app.main:app` + `npm run dev`.
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .main import app as api

_REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = Path(os.environ.get("TKMIND_FRONTEND_DIST", _REPO_ROOT / "frontend" / "dist"))

app = FastAPI(title="TKMiND Platform", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/api", api)

if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
