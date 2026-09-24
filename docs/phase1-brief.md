# Build brief: PixelRAG → TKMiND SDLC platform (Phase 1)

> **Historical document.** This is the original Phase 1 build brief, kept as written for
> reference. It predates the implementation, and some details changed during the build
> (SQLite instead of DuckDB, text-based requirements extraction, `api.py` became
> `backend/app/main.py`). The `reference/pixlerag_testing/` folder it mentions has since been
> removed; its code lives in `ai/`. See the root `CLAUDE.md` and `README.md` for the current
> state.

## Read this first

Before writing any code, read `reference/pixlerag_testing/` in full — this is the original
working PixelRAG prototype, copied in as-is: `api.py`, `app.py`, `ingest.py`, `search.py`,
`answer.py`, `embed_client.py`, `config.py`, `config.yaml`, and the Colab embedding server
notebook. Judge for yourself what's worth carrying forward versus leaving behind — don't just
take this brief's framing as final.

**This folder is reference-only. Do not edit files inside `reference/pixlerag_testing/`.** Port
whatever logic you need into the new project structure (`backend/`, `frontend/`, `ai/`) instead
of modifying the original in place.

Summarize back to me your understanding of the current architecture and data flow before
proposing changes. Do not rewrite working pieces from scratch — extend them. In particular,
preserve:

- `ingest.py`'s render → tile → embed → FAISS pipeline (`ingest_file`, `_pdf_to_images`,
  `_resize_if_needed`)
- `search.py`'s FAISS + MMR retrieval (`search`, `_mmr`)
- `answer.py`'s GPT-4o vision reranking/synthesis pattern (`_rerank_gpt4o`, `_locate_and_crop`,
  `synthesise_answer`) — this is the pattern to reuse for the new AI logic below, not a new
  pipeline
- `embed_client.py`'s `EmbedClient` wrapping the Colab/ngrok embedding server
- the `config.yaml` → `config.py` pattern for all tunable values (no hardcoded constants)
- the `.env` secrets pattern

If anything below is ambiguous or underspecified, ask me rather than guessing.

## What we're building

TKMiND is turning PixelRAG (currently a single-purpose visual document Q&A tool) into the
foundation of a client-facing SDLC platform. This phase builds exactly two modules on top of
it:

1. **Requirements & Discovery** — ingest raw requirement docs, extract structured requirements,
   flag gaps/ambiguities, let a PM review and approve them.
2. **Design review** — ingest Figma screen exports, check them against the *approved*
   requirements from module 1, and produce a recommendations report.

The unifying idea: everything both modules produce is stored in the same visual RAG index
(tiles + FAISS + metadata) that already exists — we're adding structure and workflow on top of
it, not replacing it.

## Explicitly out of scope for this phase

State these constraints back to me if you propose anything that violates them — they're
deliberate, not oversights:

- No live connectors to Jira, GitHub, Slack, or the Figma API. Upload-only for both requirement
  docs and design screens (PDF/image exports).
- No auto-writes to any external system, ever. Every AI output is advisory.
- No single numeric "alignment score." Alignment findings are categorical
  (`aligned` / `partial` / `misaligned`) with specific textual recommendations — a confident
  single number overstates what an LLM comparison can honestly guarantee.
- No development, QA, or PM/delivery modules yet. Design the data model so they can be added
  later without a rewrite (e.g. a generic `documents` table with a `doc_type` column, not
  requirement/design-specific tables bolted on ad hoc).
- No multi-tenant auth system. Single-project-at-a-time is fine for now; don't build a user
  management system as a side effect of this work.

## Users

- **PM**: uploads requirement docs, reviews/edits the extracted structure, approves it, later
  reviews the design alignment report.
- **Designer**: uploads Figma screen exports, reviews the alignment report, updates screens
  based on findings (outside this system).

Neither role is the end client of TKMiND's own clients yet — this is an internal working tool
for the project team, not a client-facing dashboard (that's a later phase).

## Functional requirements

### 1. Requirements & Discovery module

- Reuse `ingest_file` to render and tile requirement docs, but tag each document's metadata
  with `project_id` and `doc_type="requirement"`.
- New extraction step, modeled on `answer.py`'s vision-synthesis pattern: send all page images
  for a document to GPT-4o with a structured-extraction prompt. Return strict JSON:
  ```json
  {
    "epics": [{"id": "E1", "title": "..."}],
    "user_stories": [
      {"id": "S1", "epic_id": "E1", "story": "...",
       "acceptance_criteria": ["...", "..."]}
    ],
    "gaps": [{"description": "...", "page": 3, "severity": "low|medium|high"}]
  }
  ```
- Persist this structure in a new DB layer (see Data model below), versioned per project.
- Provide edit endpoints so the PM can correct extracted stories/AC before approving — don't
  make approval an all-or-nothing accept of the raw AI output.
- Approval locks that version. Only an approved version can be referenced by the design module.
  Re-opening for edits after approval creates a new version rather than mutating the approved
  one — this preserves what a design review was actually checked against.

### 2. Design review module

- Reuse `ingest_file` for Figma screen exports, tagged `doc_type="design"` and linked to the
  approved requirements version they're being checked against.
- Alignment check, one call per screen: send the screen image plus the relevant approved
  requirement text (retrieve via `search.py` against the requirements index, or pass all
  approved stories directly if the requirement set is small — use your judgment on the
  threshold) to GPT-4o vision. Return strict JSON:
  ```json
  {
    "screen_id": "...",
    "status": "aligned | partial | misaligned",
    "findings": [
      {"requirement_id": "S1", "issue": "...", "recommendation": "..."}
    ]
  }
  ```
- Persist alignment reports linked to the screen and the requirements version used.

### 3. Human-in-the-loop approval gate

- State machine for requirement versions: `draft → in_review → approved (locked)`.
- Design alignment findings are always advisory — there is no "auto-accept" or "auto-fix" path.
  The PM/designer marks individual findings as resolved or dismissed; nothing is inferred as
  resolved automatically.

### 4. Data model

Move off the current flat `metadata.json` for anything structured (keep it fine for raw
tile/FAISS metadata, but don't try to cram requirements/gaps/reports into it). Introduce
**DuckDB** as the structured data store. Two things to confirm before building the schema:

- Keep the backend to a single writer process against the local DuckDB file — DuckDB's
  concurrency model generally allows one writer at a time, unlike SQLite. This is fine at
  phase-1 scale (one PM, one designer, low volume) and is the deliberate tradeoff for getting
  fast analytical queries later (cross-project status rollups, reporting) when the PM &
  Delivery module is built.
- SQLAlchemy support for DuckDB (`duckdb_engine`) is less mature than the SQLite dialect —
  verify early that the ORM features you need (constraints, migrations) work cleanly on it
  before committing the full schema to it. If something doesn't work, raise it rather than
  working around it silently.

Rough tables:

- `projects` (id, name, created_at)
- `documents` (id, project_id, doc_type [requirement|design], version, approval_status,
  uploaded_at) — this is the generalizable table future modules will also use
- `requirement_items` (id, document_id, type [epic|story], parent_id, text, acceptance_criteria)
- `gaps` (id, document_id, description, page, severity)
- `alignment_reports` (id, design_document_id, requirements_document_id, screen_id, status,
  findings JSON)

Keep the existing FAISS index + tile PNGs as-is underneath this, referenced by `document_id`
instead of only `source`/`page`. Structured tables live in DuckDB; FAISS + tile files stay
exactly as they are today.

### 5. Backend

Extend `api.py` (don't replace it) with new routers:

- `POST /projects`, `GET /projects`
- `POST /projects/{id}/requirements` (upload + trigger extraction)
- `GET /projects/{id}/requirements/{doc_id}` (structured result + gaps)
- `PATCH /projects/{id}/requirements/{doc_id}/items/{item_id}` (edit before approval)
- `POST /projects/{id}/requirements/{doc_id}/approve`
- `POST /projects/{id}/designs` (upload screens against an approved requirements version)
- `GET /projects/{id}/designs/{doc_id}/alignment` (per-screen findings)
- `PATCH /projects/{id}/designs/{doc_id}/findings/{finding_id}` (resolve/dismiss)

### 6. Frontend

The current `app.py` Streamlit GUI was fine as a single-purpose prototype but isn't the right
shape for a real review workflow (versioned approvals, editable structured data, side-by-side
screen/findings comparison). Propose a proper frontend — React + Vite is a reasonable default
given no strong constraint from the existing stack — with at least:

- Project list / create project
- Requirements review: epics/stories/AC list, gap list with severity, inline edit, an
  Approve button that's clearly disabled or confirmed when gaps are unresolved
- Design review: screen thumbnail grid → click into a screen shows the image next to its
  findings list, each with a resolve/dismiss action

Confirm the frontend plan with me before scaffolding it — I'd rather see the page/component
breakdown first than a full app dropped in at once.

### 7. Non-functional

- All new tunable values (model names, thresholds, severities) go in `config.yaml`, following
  the existing `config.py` loader pattern — no hardcoded model strings in the new modules.
- Keep the existing embed-server error handling (`EmbedServerError`, retry logic) — the new
  ingestion paths go through the same `EmbedClient`.
- Log GPT-4o vision call counts/costs per document — these calls aren't free and volume will
  matter once this is in front of a client.
- Write tests for the extraction and alignment-check logic (mock the OpenAI client) and for the
  new API endpoints.

## How I want you to work

1. Read the repo, summarize current architecture back to me.
2. Propose the DB schema and file/module layout before writing code.
3. Build in this order: data model → requirements extraction backend → requirements review API
   → minimal frontend flow for requirements → design ingestion + alignment logic → design
   review API and frontend → tests and polish.
4. Confirm with me before any step that touches the frontend framework choice or restructures
   existing files significantly.
5. Ask rather than assume wherever this brief doesn't specify something.
