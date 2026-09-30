# TKMiND Platform

Internal SDLC tool for TKMiND project teams, built on the PixelRAG visual
document retrieval pipeline. Phase 1 covers two modules:

1. **Requirements & Discovery** — upload raw requirement docs (PDF, DOCX,
   images), extract structured epics / user stories / acceptance criteria with
   GPT-4o, flag gaps and ambiguities, let the PM edit, evaluate and approve a
   locked version.
2. **Design Review** — upload Figma screen exports against an *approved*
   requirements version; GPT-4o vision checks each screen and returns
   categorical findings (`aligned` / `partial` / `misaligned`) with
   recommendations that the PM/designer resolve or dismiss.

Every AI output is advisory — nothing is auto-accepted or written to an
external system without a human action.

## Architecture

```
frontend/  React + Vite UI  ──/api/*──►  backend/  FastAPI (port 8080)
                                              │
                    ┌─────────────────────────┼──────────────────────────┐
                    ▼                         ▼                          ▼
          SQLite (data/tkmind.db)     ai/ pipeline                 OpenAI GPT-4o
          projects, documents,        render → tile → embed        extraction, alignment,
          requirement_items, gaps,    → FAISS (data/index.faiss,   evaluation, image
          alignment reports,          data/tiles/, metadata.json)  transcription
          ai_calls (cost log), …              │
                                              ▼
                                    Embedding server (Qwen3-VL-Embedding-2B,
                                    GPU; Colab notebook exposed via ngrok)
```

| Path | What's there |
|---|---|
| `backend/app/main.py` | FastAPI app; mounts the routers |
| `backend/app/routers/` | `projects`, `requirements`, `intake` (resources + clarifying questions), `designs`, `policies` |
| `backend/app/services/` | Business logic: extraction, review/approval state machine, design alignment, evaluation, PDF + Confluence export |
| `backend/app/db/` | SQLAlchemy models and session (single serialized writer) |
| `backend/migrations/` | Alembic migrations |
| `backend/tests/` | pytest suite (OpenAI/embed server mocked) plus demo seed scripts |
| `ai/ingest/` | Ported PixelRAG ingest (`ingest_file`) and FAISS + MMR search |
| `ai/text/` | Text-layer extraction for PDF/DOCX and the requirements extractor |
| `ai/vision/` | GPT-4o vision: alignment checker, image transcription, answer synthesis |
| `ai/embed_client.py` | `EmbedClient` for the embedding server (retry + `EmbedServerError`) |
| `frontend/src/` | Pages: Requirements review, Design review, Standing policies |
| `config.yaml` / `config.py` | All tunable values (models, token limits, thresholds, cost rates) |
| `embed_server/` | Colab notebook that runs the embedding server |
| `CLAUDE.md` | Conventions and constraints for Claude Code sessions |
| `docs/phase1-brief.md` | Original Phase 1 build brief (historical) |

## Prerequisites

- Python 3.12
- Node.js 20+
- An OpenAI API key
- A running embedding server (see below)

## Setup

All commands run from the repo root (PowerShell shown; on macOS/Linux use
`.venv/bin/...` instead of `.venv\Scripts\...`).

**1. Backend dependencies**

```powershell
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt
```

**2. Secrets** — copy `.env.example` to `.env` and fill in:

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | yes | GPT-4o extraction, alignment, evaluation, transcription |
| `AWS_PROFILE` | yes, for design uploads | AWS profile used for Bedrock embeddings locally (`adlc`) |
| `EMBED_API_URL` | only with `embed_provider: http` | Base URL of the self-hosted Qwen3-VL embedding server |
| `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`, `CONFLUENCE_SPACE_KEY` | optional | Only for "Publish to Confluence"; returns 503 if unset |
| `ANTHROPIC_API_KEY` | no | Unused while `extraction_model` is `gpt-4o` |
| `JINA_API_KEY` | no | Only if `reranker` is set to the Jina model |

Never commit `.env`.

**3. Database**

```powershell
cd backend
..\.venv\Scripts\alembic upgrade head
cd ..
```

This creates `data/tkmind.db`. The FAISS index, tiles and uploads under
`data/` are created on first ingestion.

**4. Frontend dependencies**

```powershell
cd frontend
npm install
cd ..
```

## Embeddings

Design screens are embedded into the FAISS index with **Cohere Embed v4 on
Amazon Bedrock** (`embed_provider: bedrock` in `config.yaml`). This is a
managed, pay-per-call service, so no GPU is needed. Locally it uses your
AWS login: set `AWS_PROFILE=adlc` in `.env` and run `aws sso login
--profile adlc`. On AWS the server's role is used automatically.

The previous self-hosted model (Qwen3-VL via
`embed_server/colab_embed_server.ipynb` or `embed_server/server.py`) is still
available with `embed_provider: http` and `EMBED_API_URL` in `.env`. The two
produce incompatible vectors, so switching providers means rebuilding
`data/index.faiss`.

## Deployment

ADLC runs on AWS ECS Fargate, deployed with Pulumi. Pushing to `main`
builds the container image and pushes it to Amazon ECR through GitHub
Actions. [infra/README.md](infra/README.md) covers the architecture,
deploying new code, and day-to-day operations.

## Running locally

Start the backend and frontend in two terminals:

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8080 --app-dir backend
```

```powershell
npm run dev --prefix frontend
```

- UI: http://localhost:5173 (Vite proxies `/api/*` to the backend and strips the prefix)
- API docs (Swagger): http://localhost:8080/docs
- Health check: http://localhost:8080/health

## Workflow

1. **Create a project** in the project bar.
2. **Requirements** — upload a requirements doc, or stage several intake
   resources (docs, whiteboard photos) and run extraction on them together.
   Review the extracted epics/stories/AC and gaps, answer clarifying
   questions, edit or add items, run an evaluation, then **Approve**.
   Approval locks the version; further edits create a new version. Change
   requests can be uploaded against an approved version.
3. **UI/UX prompts** — on an *approved* version, pick an epic, choose which of
   its stories to include, and choose a mode: **New platform** (design system,
   app shell, first flows), **New feature** (reuses the saved design system) or
   **Edit existing** (targeted change; optionally attach a screenshot of the
   current screen). An optional style brief (reference brand such as Apple,
   primary color, tone, light/dark, platform) is saved per project. The result
   is a Figma Make prompt you can edit, copy, regenerate or delete; screens
   and states are labelled with story ids so developers can trace designs back
   to requirements. Prompts are marked *Outdated* when a newer requirements
   version supersedes theirs. Nothing is sent to Figma.
4. **Design review** — upload screen exports against the approved version.
   Each screen gets an alignment report; click a screen to see it next to its
   findings and mark each one resolved or dismissed.
5. **Share** the approved version. **Export PDF** and **Publish to
   Confluence** produce a business requirements document for stakeholders
   (scope, numbered business requirements, assumptions and dependencies,
   open issues, version history, sign-off). **Delivery PDF** gives the
   delivery team the full stories with Given/When/Then scenarios and error
   handling.

Requirement versions move `draft → in_review → approved (locked)`.

## Configuration

Edit `config.yaml`; no code changes needed. Key settings:

- `extraction_model`, `alignment_model`, `intake_image_model` — model names
- `extraction_max_tokens`, `alignment_max_tokens` — output token ceilings
- `alignment_max_stories_inline` — above this many approved stories the
  alignment check raises instead of silently truncating
- `pdf_dpi`, `max_tile_px` — ingestion rendering
- `gpt4o_*_cost_per_million` — rates used for the per-call cost log in the
  `ai_calls` table (update when pricing changes)

## Tests

```powershell
cd backend
..\.venv\Scripts\python -m pytest
```

The suite mocks the OpenAI client and embedding server and runs against an
isolated temp directory (`TKMIND_DATA_DIR` / `TKMIND_DB_PATH`), so it never
touches your real `data/`.

### Demo data

`backend/tests/seed_demo_data.py`, `seed_design_demo.py` and
`seed_bbox_demo.py` populate the local database with sample projects; the
matching `clear_*.py` scripts remove them. These write to the real `data/`
directory.

## Resetting local data

Stop the backend, delete everything inside `data/`, then run
`alembic upgrade head` again. The FAISS index and the database must be reset
together — tiles are linked to documents by `document_id`.

## Scope (phase 1)

Deliberately out of scope: live Jira/GitHub/Slack/Figma connectors
(upload-only), automatic writes to external systems, a single numeric
alignment score, development/QA/delivery modules, and multi-user auth. See
`docs/phase1-brief.md` for the reasoning.
