# VIRIYA (วิริยะ) — *Relentlessly Relevant*

Multi-tenant agentic RAG (Retrieval-Augmented Generation) platform for Thai university faculties. VIRIYA answers curriculum and academic-process questions for graduate students through LINE Official Account, drawing answers directly from each program's own documents.

## What VIRIYA does

- **Students** ask questions in Thai through the program's LINE Official Account ("วันสอบจะเริ่มเมื่อไหร่ครับ", "วิธีขอลาพักการศึกษาทำยังไง", etc.).
- The system retrieves relevant passages from program documents (PDF, Word, Excel, slides) stored in Google Drive, then composes a grounded answer with citations using Claude Opus 4.7.
- **Program staff** manage tenant settings, upload new documents, view chat logs, and check analytics through a separate Admin Portal.
- Each program is a separate **tenant** with its own knowledge base, persona, and LINE OA channel. The system is designed to scale across many programs without per-tenant code changes.

## Architecture overview

Three Python microservices on Google Cloud Run, plus a Next.js frontend, plus managed third-party APIs.

```
                     LINE OA (per tenant)
                          │
                          ▼
  ┌────────────────────────────────────────────────┐
  │  chat-api          (FastAPI + Uvicorn)          │
  │  - LINE webhook                                 │
  │  - Agentic loop (Claude Opus 4.7 + tool use)    │
  │  - Hybrid search (Pinecone + BM25 + Cohere)     │
  └────────┬───────────────────────────┬────────────┘
           │                           │
           ▼                           ▼
    Pinecone (vector store)       Firestore (tenants, logs)
           ▲                           ▲
           │                           │
  ┌────────┴────────────┐    ┌─────────┴───────────┐
  │  ingest-worker      │    │  admin-api          │
  │  (FastAPI)          │    │  (FastAPI)          │
  │  - PDF/Word/Excel   │    │  - Tenant CRUD      │
  │    via Opus vision  │    │  - User auth        │
  │  - Drive scan       │    │  - Analytics        │
  │  - Smart re-ingest  │    │  - Backups          │
  └─────────────────────┘    └──────────┬──────────┘
                                        │
                                        ▼
                            admin-portal (Next.js · separate repo)
```

Services and their roles:

| Service | Path | Purpose |
|---|---|---|
| `chat-api` | `chat/` | LINE webhook + agentic RAG + hybrid search + chat logging |
| `ingest-worker` | `ingest/` | Document pipeline (PDF/Word/Excel/Slides → text chunks → Pinecone) using Opus 4.7 universal parser |
| `admin-api` | `admin/` | Tenants, users, analytics, privacy, backup endpoints |
| `shared/` | `shared/` | Config, schemas, middleware, auth, LLM factory, Firestore + Pinecone clients |

## Tech stack

- **Language**: Python 3.11
- **Framework**: FastAPI + Uvicorn
- **Agent / LLM**: Claude Opus 4.7 (`claude-opus-4-7`) for main agent and document parsing; Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) for utility tasks (query rewrite, decomposition, multi-query)
- **Embeddings**: Cohere `embed-v4.0` (1536 dimensions)
- **Reranker**: Cohere Rerank v3.5 (with retry and neutral-0.5 fallback)
- **Vector store**: Pinecone serverless (one namespace per tenant)
- **Database**: Google Cloud Firestore (tenants, chat logs, users)
- **File storage**: Google Drive (source documents per tenant)
- **Hosting**: Google Cloud Run (asia-southeast1)
- **Frontend (separate repo)**: Next.js 16 + shadcn/ui

## Prerequisites

- **Python 3.11+** with `pip` and `venv`
- **Git Bash** (or any Unix-style shell on Windows; Unix paths used in this guide)
- **Google Cloud SDK** (`gcloud`) authenticated with access to GCP project `cutip-rag`
- **Anthropic API key**, **Pinecone API key**, **Cohere API key** (stored in GCP Secret Manager — no need to hold local copies if you have `gcloud` access)

GCP resources you should have access to:

- Project: `cutip-rag`
- Region: `asia-southeast1`
- Firestore database: `(default)`
- Pinecone index: `university-rag` (1536d, cosine)
- Cloud Run services: `cutip-chat-api`, `cutip-ingest-worker`, `cutip-admin-api`, `cutip-admin-portal`
- Secret Manager keys: `ANTHROPIC_API_KEY`, `PINECONE_API_KEY`, `COHERE_API_KEY`, `ADMIN_API_KEY`

## Quick start

### 1. Clone the repository

```bash
git clone https://github.com/Kurkool/cutip-rag-chatbot.git
cd cutip-rag-chatbot
```

### 2. Set up the Python environment

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

On macOS or Linux, use `.venv/bin/python` instead of `.venv/Scripts/python.exe`.

### 3. Configure secrets

The canonical source of secrets is **GCP Secret Manager** in project `cutip-rag`. For local runs you can either fetch them on demand:

```bash
gcloud secrets versions access latest --secret=ANTHROPIC_API_KEY
```

…or copy them once into a local `.env` file (which is gitignored):

```
ANTHROPIC_API_KEY=sk-ant-...
PINECONE_API_KEY=...
COHERE_API_KEY=...
ADMIN_API_KEY=...
```

The local `.env` can go stale over time. If you see authentication errors, refresh from Secret Manager.

### 4. Run the tests

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
```

Expected: 237 backend tests pass (frontend has 29 Vitest tests in the sibling `admin-portal` repository, total 266).

### 5. Run a service locally

For example, the chat API:

```bash
.venv/Scripts/python.exe -m uvicorn chat.main:app --reload --port 8080
```

Adapt the module path (`chat.main:app`, `ingest.main:app`, `admin.main:app`) per service. See `docker-compose.yml` for the canonical local-dev setup.

## Project structure

```
cutip-rag-chatbot/
├── README.md               ← this file
├── chat/                   ← LINE webhook + agentic RAG + search
├── ingest/                 ← Document pipeline (Opus 4.7 universal parser)
├── admin/                  ← Tenants, users, analytics, privacy, backup
├── shared/                 ← config, schemas, middleware, auth, llm factory, Firestore, vectorstore
├── scripts/                ← Operational tools (audit / smoke / reingest / diag / setup) — see scripts/README.md
├── tests/                  ← 237 backend tests (pytest, asyncio auto)
├── Dockerfile              ← chat-api default (see Deploy for service-specific pattern)
├── chat/Dockerfile, ingest/Dockerfile, admin/Dockerfile
├── docker-compose.yml
├── pytest.ini
├── requirements.txt
└── .gcloudignore           ← excludes .venv/, tests/ from Cloud Build context
```

## Deploy to Cloud Run

`gcloud run deploy --source=.` does **not** accept a `--dockerfile` flag, so the pattern is to copy the service's Dockerfile to the repo root, deploy, and restore the default afterwards:

```bash
cd cutip-rag-chatbot/

# 1. Pick the service to deploy (chat | ingest | admin)
cp {service}/Dockerfile Dockerfile

# 2. Deploy with the right flags for that service
gcloud run deploy cutip-{service}-api \
  --source=. \
  --region=asia-southeast1 \
  --project=cutip-rag \
  --set-secrets "PINECONE_API_KEY=PINECONE_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,COHERE_API_KEY=COHERE_API_KEY:latest,ADMIN_API_KEY=ADMIN_API_KEY:latest" \
  --quiet

# 3. Restore the default chat Dockerfile
git checkout Dockerfile
```

Service-specific flags you should know:

| Service | Extra flags |
|---|---|
| `chat-api` | `--min-instances=1` (avoid LINE webhook cold-start timeout) |
| `ingest-worker` | `--timeout=3600` (long batch ingests) |
| `admin-api` | `--timeout=600` (Pinecone backup headroom) |

Cloud Run service URLs (stable):

```
https://cutip-{service}-265709916451.asia-southeast1.run.app
```

where `{service}` is `chat-api`, `ingest-worker`, `admin-api`, or `admin-portal`.

## Operational tooling

`scripts/` contains 16 standalone Python scripts grouped by purpose. See `scripts/README.md` for the full catalogue. Run pattern:

```bash
PYTHONPATH=. .venv/Scripts/python.exe scripts/<subdir>/<name>.py
```

Common operations:

```bash
# Full audit (source vs Pinecone + retrieval probes) — run before any production data change
PYTHONPATH=. .venv/Scripts/python.exe scripts/audit/full_audit.py

# 20 adversarial bot probes
PYTHONPATH=. .venv/Scripts/python.exe scripts/audit/ask_anything.py

# Compare v1 prod (cutip_01) vs v2 pilot (cutip_v2_audit) Pinecone namespaces
PYTHONPATH=. .venv/Scripts/python.exe scripts/audit/compare_v1_v2.py

# Trigger full re-ingest of a tenant's Drive folder
PYTHONPATH=. .venv/Scripts/python.exe scripts/reingest/reingest_all.py

# Quick smoke test
PYTHONPATH=. .venv/Scripts/python.exe scripts/smoke/smoke_test.py
```

The `audit/` and `diag/` scripts fetch secrets from GCP Secret Manager on demand, so you do not need to hold local copies of the API keys when running them.

## Critical gotchas

Cross-machine pitfalls you will hit if you are not aware of them. These are the ones most likely to surprise a new maintainer.

1. **Opus 4.7 adaptive thinking returns a list of content blocks, not a string.** Both `chat/services/agent.py::run_agent` and `ingest/services/vision.py::parse_page_image` extract text blocks explicitly. If you miss this when adding a new code path, you get intermittent 500 errors with a stringified Python list as the answer.

2. **Thinking + forced `tool_choice` returns 400.** Use `tool_choice={"type": "auto"}` and instruct the tool call from the system prompt. This was empirically required for long multimodal documents (a 45-page slide deck went from 0 chunks to 43 once we made this change).

3. **Opus tool output needs `max_tokens=32000`.** A 23-entry JSON array silently truncates at 8K with the default 4096. There is no warning — you just get a shorter array.

4. **LangGraph silently returns "Sorry, need more steps..." when `remaining_steps < 2` with pending tool calls.** This is not an exception. The agent detects it and substitutes a clearer message (see `chat/services/agent.py::_LANGGRAPH_STEPS_FALLBACK`).

5. **`gcloud run deploy --source=.` does not accept `--dockerfile`.** Copy the right Dockerfile to the repo root before deploy (see [Deploy](#deploy-to-cloud-run)). Forgetting this deploys the chat-api code to whichever service you intended.

6. **LibreOffice needs Thai fonts.** The ingest container installs `fonts-thai-tlwg` and runs `fc-cache -f` to render Thai correctly in XLSX/PPTX → PDF conversion. Without these fonts, Thai text becomes □ boxes, Opus vision sees boxes, and chunks come back as "ไม่สามารถถอดความได้".

7. **Anthropic workspace ≠ credits.** "Credit balance too low" despite the console showing balance usually means the API key is tied to a different workspace from the one that was topped up. Generate a new key in the funded workspace.

8. **Always set `sys.stdout.reconfigure(encoding='utf-8')` at the top of any script that prints Thai, emoji, or arrows on Windows.** Otherwise cp874 crashes the script with `UnicodeEncodeError`. All existing scripts in `scripts/` follow this pattern.


## Related repository

The frontend admin portal lives in a separate public repository: `admin-portal` (Next.js 16 + shadcn/ui). Program staff use it to manage tenant settings, upload documents to the knowledge base, review chat logs, and inspect analytics.

## Contributing

Conventions used throughout the codebase:

- **Test-driven development**: failing test → minimal implementation → passing test → commit.
- **One file per concern** in `chat/services/`, `ingest/services/`, etc. Keep modules small and focused.
- **No `temperature`, `top_p`, `top_k`** when calling Opus 4.7 — the model rejects them.
- **Branch convention**: `master` is production; `legacy` preserves the pre-v2 architecture for reference only (do not merge forward).
- Run the test suite before pushing: `.venv/Scripts/python.exe -m pytest tests/ -q`.

## License

Released under the MIT License. See `LICENSE` for the full text.

## Contact

For questions about the project, reach out via the issue tracker on GitHub or contact the maintainers directly.
