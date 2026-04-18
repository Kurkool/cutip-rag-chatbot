# Split Services — Microservices Architecture Design Spec

## Overview

Split the CU-TIP RAG monolith (`cutip-rag-chatbot/`) into 3 Cloud Run microservices with shared code, within a single monorepo.

**Decisions:**
- Routing: Option A — 3 separate Cloud Run URLs (no API Gateway)
- Code: Monorepo with `shared/` package (not separate repos)
- Keep `main.py` monolith for local dev
- Admin-portal adds `NEXT_PUBLIC_INGEST_URL` env var

---

## Service Architecture

### Service 1: Chat API (`cutip-chat-api`)
- **Purpose:** Answer student questions via LINE webhook and /api/chat
- **Endpoints:** POST /webhook/line, POST /api/chat, GET /health
- **Dependencies:** Claude Opus (LLM), Cohere embed+rerank, Pinecone, Firestore, BM25, Claude Haiku (multi-query, decomposition, summarization)
- **Does NOT need:** LibreOffice, pymupdf, pandas, Google Drive API, GCS
- **Resources:** 1 GB RAM, 2 CPU, auto-scale 1-10
- **Called by:** LINE OA, Admin Portal (chat test)

### Service 2: Ingestion Worker (`cutip-ingest-worker`)
- **Purpose:** Process documents → chunk → enrich → embed → upsert to Pinecone
- **Endpoints:** POST /api/tenants/{id}/ingest/*, GET/DELETE /api/tenants/{id}/documents, GET /health
- **Dependencies:** Claude Haiku (Vision + enrichment), Cohere embed, Pinecone, Firestore, LibreOffice, pymupdf, pandas, openpyxl, Google Drive API, SemanticChunker
- **Does NOT need:** Claude Opus, Cohere reranker, BM25, conversation memory
- **Resources:** 2 GB RAM, 2 CPU, 1-2 instances
- **Called by:** Admin Portal (upload/Drive), Cloud Scheduler (hourly scan)

### Service 3: Admin API (`cutip-admin-api`)
- **Purpose:** CRUD tenants/users, analytics, billing, backup, privacy, registration
- **Endpoints:** /api/tenants/*, /api/users/*, /api/tenants/{id}/analytics, /api/tenants/{id}/chat-logs, /api/tenants/{id}/usage, /api/usage, /api/backups/*, /api/privacy/*, /api/auth/register, /api/registrations/*, GET /health
- **Dependencies:** Firebase Admin SDK, Firestore, Pinecone (admin ops), GCS (backup)
- **Does NOT need:** Claude (Opus or Haiku), Cohere (embed or rerank), LibreOffice, pymupdf, pandas, Google Drive API, BM25
- **Resources:** 512 MB RAM, 1 CPU, 1-2 instances
- **Called by:** Admin Portal (all pages except ingest)

---

## Monorepo Structure

### Current (flat monolith):
```
cutip-rag-chatbot/
├── main.py, config.py, schemas.py
├── routers/ (8 files)
├── services/ (18 files)
├── tests/ (17 files)
├── Dockerfile, requirements.txt
```

### Target (microservices):
```
cutip-rag-chatbot/
├── shared/                        # Common code (Python package)
│   ├── __init__.py
│   ├── config.py                  # from config.py
│   ├── schemas.py                 # from schemas.py
│   ├── middleware.py              # NEW: CORS, logging, error handler (extracted from main.py)
│   └── services/
│       ├── __init__.py
│       ├── firestore.py           # from services/firestore.py
│       ├── auth.py                # from services/auth.py
│       ├── embedding.py           # from services/embedding.py
│       ├── vectorstore.py         # from services/vectorstore.py
│       ├── usage.py               # from services/usage.py
│       ├── notifications.py       # from services/notifications.py
│       ├── dependencies.py        # from services/dependencies.py
│       └── rate_limit.py          # from services/rate_limit.py
│
├── chat/                          # Chat API microservice
│   ├── __init__.py
│   ├── main.py                    # NEW: FastAPI app with chat lifespan
│   ├── Dockerfile                 # NEW: python:3.11-slim (no LibreOffice)
│   ├── requirements.txt           # NEW: chat-specific deps
│   ├── routers/
│   │   ├── __init__.py
│   │   └── webhook.py             # from routers/webhook.py
│   └── services/
│       ├── __init__.py
│       ├── agent.py               # from services/agent.py
│       ├── tools.py               # from services/tools.py
│       ├── search.py              # from services/search.py
│       ├── bm25.py                # from services/bm25.py
│       ├── reranker.py            # from services/reranker.py
│       ├── memory.py              # from services/memory.py
│       └── line.py                # from services/line.py
│
├── ingest/                        # Ingestion Worker microservice
│   ├── __init__.py
│   ├── main.py                    # NEW: FastAPI app with ingest lifespan
│   ├── Dockerfile                 # NEW: python:3.11-slim + LibreOffice
│   ├── requirements.txt           # NEW: ingest-specific deps
│   ├── routers/
│   │   ├── __init__.py
│   │   └── ingestion.py           # from routers/ingestion.py
│   └── services/
│       ├── __init__.py
│       ├── ingestion.py           # from services/ingestion.py
│       ├── vision.py              # from services/vision.py
│       └── gdrive.py              # from services/gdrive.py
│
├── admin/                         # Admin API microservice
│   ├── __init__.py
│   ├── main.py                    # NEW: FastAPI app with admin lifespan
│   ├── Dockerfile                 # NEW: python:3.11-slim (lightest)
│   ├── requirements.txt           # NEW: admin-specific deps
│   └── routers/
│       ├── __init__.py
│       ├── tenants.py             # from routers/tenants.py
│       ├── users.py               # from routers/users.py
│       ├── analytics.py           # from routers/analytics.py
│       ├── backup.py              # from routers/backup.py
│       ├── privacy.py             # from routers/privacy.py
│       └── registration.py        # from routers/registration.py
│
├── tests/                         # Restructured tests
│   ├── conftest.py                # Shared fixtures
│   ├── chat/                      # Chat service tests
│   ├── ingest/                    # Ingest service tests
│   └── admin/                     # Admin service tests
│
├── main.py                        # KEEP: monolith for local dev (imports all)
├── requirements.txt               # KEEP: all deps for local dev
└── docker-compose.yml             # NEW: run all 3 locally
```

---

## Import Changes

All imports update from flat to package-based:

```python
# Before (flat):
from config import settings
from services.firestore import _get_db
from services.auth import require_super_admin

# After (shared package):
from shared.config import settings
from shared.services.firestore import _get_db
from shared.services.auth import require_super_admin
```

Service-specific imports stay relative within their directory:
```python
# In chat/services/agent.py:
from chat.services.tools import create_tools
from chat.services.memory import conversation_memory

# In ingest/services/ingestion.py:
from ingest.services.vision import parse_page_image
```

---

## Dockerfiles

### chat/Dockerfile
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY shared/ /app/shared/
COPY chat/ /app/chat/
COPY chat/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "chat.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### ingest/Dockerfile
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-core libreoffice-writer && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY shared/ /app/shared/
COPY ingest/ /app/ingest/
COPY ingest/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "ingest.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### admin/Dockerfile
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY shared/ /app/shared/
COPY admin/ /app/admin/
COPY admin/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "admin.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Requirements per Service

### chat/requirements.txt
```
fastapi
uvicorn
langchain-anthropic
langchain-core
langgraph
langchain-pinecone
langchain-experimental
cohere
pinecone
rank-bm25
httpx
slowapi
google-cloud-firestore
```

### ingest/requirements.txt
```
fastapi
uvicorn
langchain-anthropic
langchain-core
langchain-pinecone
langchain-experimental
langchain-text-splitters
cohere
pinecone
pymupdf
pandas
openpyxl
python-docx
google-api-python-client
google-auth-httplib2
httpx
slowapi
google-cloud-firestore
```

### admin/requirements.txt
```
fastapi
uvicorn
pinecone
httpx
slowapi
google-cloud-firestore
google-cloud-storage
firebase-admin
```

---

## External Wiring Changes

### LINE OA Webhook URL
```
Before: https://cutip-rag-bot-....run.app/webhook/line
After:  https://cutip-chat-api-....run.app/webhook/line
```
Update in LINE Developers Console.

### Cloud Scheduler Jobs
```
cutip-01-auto-scan:
  Before: https://cutip-rag-bot-....run.app/api/tenants/cutip_01/ingest/gdrive/scan
  After:  https://cutip-ingest-worker-....run.app/api/tenants/cutip_01/ingest/gdrive/scan

cutip-backup-daily:
  Before: https://cutip-rag-bot-....run.app/api/backups/firestore
  After:  https://cutip-admin-api-....run.app/api/backups/firestore

cutip-retention-cleanup:
  Before: https://cutip-rag-bot-....run.app/api/privacy/retention/cleanup
  After:  https://cutip-admin-api-....run.app/api/privacy/retention/cleanup
```

### Admin Portal (.env.production)
```
NEXT_PUBLIC_API_URL=https://cutip-admin-api-....run.app
NEXT_PUBLIC_INGEST_URL=https://cutip-ingest-worker-....run.app
```

Admin Portal api.ts: ingest-related API calls use `INGEST_URL`, everything else uses `API_URL`.

### Cloud Monitoring Uptime Check
Add health checks for all 3 services (currently only checks monolith).

---

## Migration Strategy (Zero Downtime)

1. Deploy 3 new services alongside monolith (monolith keeps running)
2. Test each new service with curl
3. Switch LINE webhook → chat-api
4. Switch Cloud Scheduler → ingest-worker + admin-api
5. Update admin-portal env vars → redeploy
6. Verify everything works
7. Delete monolith Cloud Run service

---

## Docker Compose (Local Dev)

```yaml
services:
  chat:
    build:
      context: .
      dockerfile: chat/Dockerfile
    ports: ["8001:8000"]
    env_file: .env

  ingest:
    build:
      context: .
      dockerfile: ingest/Dockerfile
    ports: ["8002:8000"]
    env_file: .env

  admin:
    build:
      context: .
      dockerfile: admin/Dockerfile
    ports: ["8003:8000"]
    env_file: .env
```

Or keep using `main.py` monolith for local dev: `uvicorn main:app --port 8000`
