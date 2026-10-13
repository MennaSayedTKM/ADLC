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
- `ai/text/ux_prompt_generator.py` — Figma Make prompt generation, "Lego" style: one **Platform
  Blueprint** per project (mode `foundation`, no epic: vision, design system, app shell, a
  nav placeholder per epic) and one prompt per epic (`new_feature` / `edit_existing`). Service:
  `backend/app/services/ux_prompts.py`; only from *approved* requirement versions. Consistency
  comes from a context pack (tokens, sitemap, screen registry derived from saved prompts,
  components, feature relationship map) built per feature prompt. Prompts live in `ux_prompts`;
  the PM's brief and the blueprint's outputs live in `projects.style_brief`.
- `backend/app/services/use_case_diagrams.py` — a UML use-case diagram per story in the business
  requirements document (PDF + Confluence). The model (`ai/text/use_case_generator.py`) returns
  structured actors/use cases, our code writes the PlantUML text, `plantuml_renderer.py` renders it
  locally with `java -jar tools/plantuml.jar` (never an outside service). Generated automatically at
  export time, cached in `use_case_diagrams` by story-content hash. Optional: without Java/the jar
  exports omit diagrams. Tests blank `PLANTUML_JAR` (conftest) and stub the renderer.
- `backend/app/services/style_reference.py` — reads a reference website's HTML/CSS (BeautifulSoup)
  into style tags. It fetches a user-supplied URL, so SSRF guards are mandatory (public IPs only,
  80/443 only, per-redirect checks, size/time caps) — keep them and their tests if you touch it.
- `ai/vision/` — GPT-4o vision: design alignment checker, intake image transcription,
  screenshot description for edit prompts (`describe_screen.py`), rerank/answer synthesis
  (kept for future Q&A)
- `ai/bedrock_embed_client.py` — **default** embedding client: Cohere Embed v4 on Amazon
  Bedrock (`embed_provider: bedrock` in `config.yaml`). Same interface as `EmbedClient`.
- `ai/embed_client.py` — `EmbedClient` for the self-hosted Qwen3-VL server (retry +
  `EmbedServerError`), used when `embed_provider: http`
- `embed_server/` — Qwen3-VL embedding server: `server.py` (optional AWS GPU instance) and
  the original Colab notebook. Keep their model, prompts and pooling identical. Its vectors
  are incompatible with Cohere's — never mix providers in one FAISS index.
- `infra/` — Pulumi (Python) deployment to AWS: one Control Tower member account, eu-central-1.
  ECS Fargate (exactly one task — single-writer SQLite) behind an ALB + Cognito, `data/` on
  EFS, image in ECR. See `infra/README.md`. Infra tests run offline:
  `cd infra; venv\Scripts\python -m pytest tests`
- `Dockerfile`, `docker/entrypoint.sh`, `backend/app/serve.py` — the production container: one
  uvicorn process serving the API under `/api` and the built frontend at `/`
- `.github/workflows/docker-publish.yml` — tests, builds and pushes the image to ECR on push to
  `main` (OIDC, no stored AWS keys). Tests must pass without a `.env` (CI has none).
- `frontend/src/` — React + Vite + TypeScript; `api/client.ts` calls `/api/*`. Guided-workflow UI:
  a left-nav shell, a six-step lifecycle stepper on every project page, and pages Projects home,
  Overview, Sources, Requirements, Design, Validate design, Publish & export, Company standards,
  Settings. See `frontend/README.md` for the layout and the rules below.
  - Hash routing in `lib/router.ts` (no router dependency). `state/ProjectContext` loads a project's
    sources/requirements/design once; the lifecycle stepper, "next best step" and every page read it.
    Lifecycle state is **derived** (`lib/lifecycle.ts`), never stored.
  - Long runs (generate requirements, check a design) live in `ProjectContext`, not in a page, so they
    keep going if the user navigates away.
  - Labels are task language ("Sources", "Company standards", "Generate requirements"); API names
    (`intake_resources`, `standing_policies`) are unchanged.
  - Accessibility is a requirement: text ≥ 4.5:1 contrast in **both** themes, nothing under 12px, status
    never by colour alone (icon + label), visible focus, keyboard reachable. Use tokens from `index.css`,
    not raw hex values, and no `opacity` on text.
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

- No live connectors to Jira, GitHub, Slack or the Figma API; inputs are uploads. The one
  outbound read is the PM-triggered, read-only fetch of a reference website's public HTML/CSS.
- No automatic writes to external systems. Every AI output is advisory, and anything
  outbound (e.g. Confluence publish) needs an explicit user action.
- Findings stay categorical (`aligned` / `partial` / `misaligned`) with textual recommendations, and
  are resolved or dismissed only by a person. The UI also shows a summary alignment percentage
  (aligned screens count fully, partial half — `lib/design.ts`); it is a display aid derived from those
  categories, never stored and never used to gate approval or publishing.
- No multi-user auth or user management; single project at a time.
- Development, QA and PM/delivery modules are later phases. Keep the data model open to them.

## How I want you to work

- Ask rather than assume wherever something is underspecified.
- Confirm before changing the frontend framework, restructuring existing files significantly,
  or deleting data.
- Propose schema changes before writing the migration.
