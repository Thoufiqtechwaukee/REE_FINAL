# REE FINAL — Resume Depth Evaluation Engine

A resume understanding and evaluation platform: PDF → dynamic section mapping →
semantic chunking → Nomic embeddings → FAISS retrieval → controlled technical
skill/role catalogs → user-verified skill gate → four-category evaluation
(Completeness / Growth / Evidence / Experience, /25 each, /100 total) reasoned
over with Qwen and scored deterministically in Python.

## Prerequisites

- Python 3.12+
- SQL Server (local or remote), with ODBC Driver 17 or 18 for SQL Server installed
- A reachable Ollama-compatible RunPod endpoint serving `qwen2.5:14b` (chat) and
  `nomic-embed-text` (embeddings) at `/v1/chat/completions` and `/v1/embeddings`

## Setup

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"          # Windows
# source .venv/bin/activate && pip install -e ".[dev]"   # macOS/Linux

cp .env.example .env
# edit .env: RUNPOD_ENDPOINT_URL, DATABASE_URL (defaults to a local
# REEFinalDB via Windows Trusted Connection)
```

Create the database (SQL Server must already be running):

```sql
CREATE DATABASE REEFinalDB;
```

Run migrations:

```bash
.venv/Scripts/alembic upgrade head
```

Seed the Technical Skill Catalog and Role Catalog (idempotent — safe to re-run
after editing the seed JSON files under `app/taxonomy/`):

```bash
.venv/Scripts/python scripts/seed_taxonomy.py
.venv/Scripts/python scripts/embed_catalogs.py   # embeds + indexes both catalogs into FAISS
```

Run the server:

```bash
.venv/Scripts/uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/` — upload a PDF resume, review/confirm detected
skills, and run the evaluation.

## Tests

```bash
.venv/Scripts/pytest tests/unit -v
```

Covers the deterministic core: date/overlap/gap math (including the proven
interval-union regression case), section mapping, generic-noun skill
rejection, responsibility-language classification, seniority classification
(including the ambiguous-bare-title escalation path), and scoring math.

## Architecture

See `app/` — `extraction/` → `chunking/` → `embeddings/` + `vector/` →
`taxonomy/` (skill/role catalog matching) → `agents/` (Qwen-backed
Experience/Evidence/Growth/Completeness/Final-Justification) →
`evaluation/` (deterministic scoring + orchestration) → `api/routes/`.
`frontend/` is a static Bootstrap 5 + vanilla JS app served by the same
FastAPI process.

Every score is computed in Python from a fixed rubric; Qwen only ever returns
categorical/ordinal verdicts (e.g. `STRONG/MODERATE/WEAK/NONE`) with cited
evidence — it never writes a number to a score field.

## Admin extensibility

The catalogs are seed data, not hardcoded lists: edit
`app/taxonomy/skills/seed_skills.json` or `app/taxonomy/roles/seed_roles.json`
and re-run `scripts/seed_taxonomy.py` (and `scripts/embed_catalogs.py` if you
added/changed entries) to add a skill/role, add an alias, or deprecate an
entry. There is no end-user "add skill" affordance anywhere in the product —
by design, only catalog data admins own can introduce a new skill or role
identity.
