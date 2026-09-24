# TKMiND Platform — guide for Claude

Internal SDLC tool for TKMiND project teams (PM + designer), built on the PixelRAG visual
retrieval pipeline. Phase 1 is built: **Requirements & Discovery** and **Design Review**.
See `README.md` for setup and the user workflow; `docs/phase1-brief.md` is the original
build brief (historical — some details changed during the build).

## Layout

- `backend/app/` — FastAPI app (`main.py`), `routers/`, `services/` (business logic),
  `schemas/` (Pydantic), `db/` (SQLAlchemy models + session), `deps.py` (client getters)
- `backend/migrations/` — Alembic; `backend/tests/` — pytest suite + demo seed scripts
- `ai/ingest/` — PixelRAG render → tile → embed → FAISS (`ingest_file`) and FAISS + MMR search
- `ai/text/` — PDF text-layer / DOCX extraction and the requirements extractor
- `ai/vision/` — GPT-4o vision: design alignment checker, intake image transcription,
  rerank/answer synthesis (kept for future Q&A)
- `ai/embed_client.py` — `EmbedClient` for the embedding server (retry + `EmbedServerError`)
- `embed_server/` — Qwen3-VL embedding server: `server.py` (runs on the AWS GPU instance) and
  the original Colab notebook. Keep their model, prompts and pooling identical.
- `infra/` — Pulumi (Python) deployment to AWS: one Control Tower member account, eu-central-1.
  See `infra/README.md`. Infra tests run offline: `cd infra; venv\Scripts\python -m pytest tests`
- `frontend/src/` — React + Vite + TypeScript; `api/client.ts` calls `/api/*`
- `config.yaml` + `config.py` — every tunable value; `.env` — secrets

## Commands (run from repo root, Windows)

- Backend: `.venv\Scripts\python -m uvicorn app.main:app --port 8080 --app-dir backend`
- Frontend: `npm run dev --prefix frontend` (port 5173, proxies `/api` → 8080, strips prefix)
- Migrations: `cd backend; ..\.venv\Scripts\alembic upgrade head`
- Tests: `cd backend; ..\.venv\Scripts\python -m pytest`
- Frontend checks: `npm run build --prefix frontend` (runs `tsc -b`), `npm run lint --prefix frontend`

## Conventions

- **No hardcoded model names, token limits, thresholds or prices.** Add them to `config.yaml`
  and expose them through `config.py` with `_require(...)`.
- **Log every AI call** to the `ai_calls` table with tokens and estimated cost. New call
  types need a migration, because `call_type` has a CHECK constraint.
- **Data model:** structured data in SQLite (`data/tkmind.db`); tiles, the FAISS index and
  `metadata.json` in `data/`, linked by `document_id`. `documents` is the generic table
  (`doc_type`: `requirement` | `design` | `change_request`). Future modules should add a
  `doc_type`, not new document tables. Status columns are enforced by CHECK constraints.
- **Migrations:** any schema change goes through a new Alembic revision using
  `batch_alter_table` (SQLite can't alter constraints in place), never `create_all` on the
  real DB.
- **Single writer:** all DB access goes through the locked session in `db/session.py`, and the
  FAISS index is held in-process, so the backend runs as one uvicorn worker. Don't add
  anything that assumes multiple processes.
- **Approval gate:** requirement versions go `draft → in_review → approved`. Approved versions
  are locked; editing after approval creates a new version. Design reviews reference the
  approved version they were checked against.
- **Tests** mock OpenAI and the embed server, and run against an isolated temp dir via
  `TKMIND_DATA_DIR` / `TKMIND_DB_PATH` (set in `conftest.py`). Never let tests touch the real
  `data/`. New extraction/alignment logic and new endpoints need tests.
- **Extend, don't rewrite:** the ported PixelRAG pieces (`ingest_file`, `search`/`_mmr`,
  `EmbedClient`, the GPT-4o vision pattern in `ai/vision/`) are the foundation. Build on them.

## Scope constraints (deliberate — flag anything that would break them)

- No live connectors to Jira, GitHub, Slack or the Figma API; inputs are uploads.
- No automatic writes to external systems. Every AI output is advisory, and anything
  outbound (e.g. Confluence publish) needs an explicit user action.
- No single numeric alignment score. Findings are categorical (`aligned` / `partial` /
  `misaligned`) with textual recommendations, and are resolved or dismissed only by a person.
- No multi-user auth or user management; single project at a time.
- Development, QA and PM/delivery modules are later phases. Keep the data model open to them.

## How I want you to work

- Ask rather than assume wherever something is underspecified.
- Confirm before changing the frontend framework, restructuring existing files significantly,
  or deleting data.
- Propose schema changes before writing the migration.
