"""
main.py
TKMiND platform FastAPI app. Extends the original PixelRAG api.py with the
new Requirements & Discovery and Design Review routers, on top of the same
ingest/search/answer pipeline in ai/.
"""

import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

load_dotenv(_REPO_ROOT / ".env")

from .routers import designs, intake, policies, projects, requirements  # noqa: E402

app = FastAPI(
    title="TKMiND Platform API",
    description="SDLC platform built on PixelRAG's visual document retrieval.",
    version="0.1.0",
)

app.include_router(projects.router)
app.include_router(requirements.router)
app.include_router(intake.router)
app.include_router(intake.questions_router)
app.include_router(policies.router)
app.include_router(designs.router)


@app.get("/health", summary="Liveness check")
def health():
    return {"status": "ok"}
