# Split Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the CU-TIP RAG monolith into 3 Cloud Run microservices (Chat API, Ingestion Worker, Admin API) with shared code package, zero-downtime migration.

**Architecture:** Monorepo with `shared/` Python package for common code (config, firestore, auth, vectorstore, embedding, usage). Each service has its own `main.py`, `Dockerfile`, `requirements.txt`. Services communicate with external systems (Firestore, Pinecone, LINE) directly — no inter-service calls.

**Tech Stack:** FastAPI, Cloud Run, Docker, existing deps split across services

**Spec:** `docs/superpowers/specs/2026-04-15-split-services-design.md`

---

## File Structure

### Files to CREATE:
- `shared/__init__.py`, `shared/config.py`, `shared/schemas.py`, `shared/middleware.py`
- `shared/services/__init__.py`, `shared/services/firestore.py`, `shared/services/auth.py`, `shared/services/embedding.py`, `shared/services/vectorstore.py`, `shared/services/usage.py`, `shared/services/notifications.py`, `shared/services/dependencies.py`, `shared/services/rate_limit.py`, `shared/services/backup.py`
- `chat/__init__.py`, `chat/main.py`, `chat/Dockerfile`, `chat/requirements.txt`
- `chat/routers/__init__.py`, `chat/routers/webhook.py`
- `chat/services/__init__.py`, `chat/services/agent.py`, `chat/services/tools.py`, `chat/services/search.py`, `chat/services/bm25.py`, `chat/services/reranker.py`, `chat/services/memory.py`, `chat/services/line.py`
- `ingest/__init__.py`, `ingest/main.py`, `ingest/Dockerfile`, `ingest/requirements.txt`
- `ingest/routers/__init__.py`, `ingest/routers/ingestion.py`
- `ingest/services/__init__.py`, `ingest/services/ingestion.py`, `ingest/services/vision.py`, `ingest/services/gdrive.py`
- `admin/__init__.py`, `admin/main.py`, `admin/Dockerfile`, `admin/requirements.txt`
- `admin/routers/__init__.py`, `admin/routers/tenants.py`, `admin/routers/users.py`, `admin/routers/analytics.py`, `admin/routers/backup.py`, `admin/routers/privacy.py`, `admin/routers/registration.py`
- `docker-compose.yml`

### Files to KEEP (monolith for local dev):
- `main.py`, `config.py`, `schemas.py`, `routers/`, `services/`, `tests/`, `requirements.txt`

### Files to MODIFY:
- `admin-portal/src/lib/api.ts` — split ingest calls to use INGEST_URL
- `admin-portal/.env.production` — add NEXT_PUBLIC_INGEST_URL
- `admin-portal/.env.local` — add NEXT_PUBLIC_INGEST_URL

---

## Task 1: Create shared/ package

**Files:** Create `shared/` directory with all common code copied from existing files.

- [ ] **Step 1: Create directory structure**

```bash
cd cutip-rag-chatbot
mkdir -p shared/services
```

- [ ] **Step 2: Create `shared/__init__.py`**

```python
# shared/__init__.py
```

- [ ] **Step 3: Copy config.py → shared/config.py**

```bash
cp config.py shared/config.py
```

No import changes needed — config.py has no project-internal imports.

- [ ] **Step 4: Copy schemas.py → shared/schemas.py**

```bash
cp schemas.py shared/schemas.py
```

No import changes needed — schemas.py has no project-internal imports.

- [ ] **Step 5: Create shared/services/__init__.py**

```python
# shared/services/__init__.py
```

- [ ] **Step 6: Copy shared service files**

```bash
cp services/firestore.py shared/services/firestore.py
cp services/auth.py shared/services/auth.py
cp services/embedding.py shared/services/embedding.py
cp services/vectorstore.py shared/services/vectorstore.py
cp services/usage.py shared/services/usage.py
cp services/notifications.py shared/services/notifications.py
cp services/dependencies.py shared/services/dependencies.py
cp services/rate_limit.py shared/services/rate_limit.py
cp services/backup.py shared/services/backup.py
```

- [ ] **Step 7: Update imports in all shared/ files**

In every file under `shared/`, replace:
- `from config import` → `from shared.config import`
- `from services.` → `from shared.services.`
- `from services import` → `from shared.services import`
- `from schemas import` → `from shared.schemas import`

Files to update: `shared/services/firestore.py`, `shared/services/auth.py`, `shared/services/embedding.py`, `shared/services/vectorstore.py`, `shared/services/usage.py`, `shared/services/notifications.py`, `shared/services/dependencies.py`, `shared/services/rate_limit.py`, `shared/services/backup.py`

- [ ] **Step 8: Create shared/middleware.py**

Extract CORS, logging middleware, and error handler from `main.py` lines 60-115 into a reusable module:

```python
# shared/middleware.py
"""Shared middleware for all microservices."""
import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from shared.config import settings
from shared.services.rate_limit import limiter

logger = logging.getLogger(__name__)


def setup_middleware(app: FastAPI) -> None:
    """Configure CORS, rate limiting, logging, and error handling."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = time.time() - start
        logger.info(
            "%s %s → %s (%.2fs)",
            request.method, request.url.path, response.status_code, elapsed,
        )
        return response

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        try:
            from shared.services.notifications import alert_error
            await alert_error(
                "Unhandled Error",
                f"`{type(exc).__name__}`: {str(exc)[:200]}",
                Path=str(request.url.path),
            )
        except Exception:
            pass
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. Check logs for details."},
        )
```

- [ ] **Step 9: Verify shared/ imports work**

```bash
cd cutip-rag-chatbot
PYTHONPATH=. python -c "from shared.config import settings; print('config OK:', settings.PINECONE_INDEX_NAME)"
PYTHONPATH=. python -c "from shared.services.firestore import _get_db; print('firestore OK')"
PYTHONPATH=. python -c "from shared.middleware import setup_middleware; print('middleware OK')"
```

---

## Task 2: Create chat/ service

**Files:** Create `chat/` directory with Chat API service.

- [ ] **Step 1: Create directory structure**

```bash
mkdir -p chat/routers chat/services
touch chat/__init__.py chat/routers/__init__.py chat/services/__init__.py
```

- [ ] **Step 2: Copy chat-specific files**

```bash
cp routers/webhook.py chat/routers/webhook.py
cp services/agent.py chat/services/agent.py
cp services/tools.py chat/services/tools.py
cp services/search.py chat/services/search.py
cp services/bm25.py chat/services/bm25.py
cp services/reranker.py chat/services/reranker.py
cp services/memory.py chat/services/memory.py
cp services/line.py chat/services/line.py
```

- [ ] **Step 3: Update imports in all chat/ files**

In every file under `chat/`, replace:
- `from config import` → `from shared.config import`
- `from schemas import` → `from shared.schemas import`
- `from services.firestore` → `from shared.services.firestore`
- `from services.auth` → `from shared.services.auth`
- `from services.embedding` → `from shared.services.embedding`
- `from services.vectorstore` → `from shared.services.vectorstore`
- `from services.usage` → `from shared.services.usage`
- `from services.dependencies` → `from shared.services.dependencies`
- `from services.rate_limit` → `from shared.services.rate_limit`
- `from services.notifications` → `from shared.services.notifications`

For chat-internal imports, replace:
- `from services.agent` → `from chat.services.agent`
- `from services.tools` → `from chat.services.tools`
- `from services.search` → `from chat.services.search`
- `from services.bm25` → `from chat.services.bm25`
- `from services.reranker` → `from chat.services.reranker`
- `from services.memory` → `from chat.services.memory`
- `from services.line` → `from chat.services.line`

Files to update: `chat/routers/webhook.py`, `chat/services/agent.py`, `chat/services/tools.py`, `chat/services/search.py`, `chat/services/bm25.py`, `chat/services/reranker.py`, `chat/services/memory.py`, `chat/services/line.py`

- [ ] **Step 4: Create chat/main.py**

```python
# chat/main.py
"""Chat API — LINE webhook + /api/chat endpoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from shared.config import APP_VERSION
from shared.middleware import setup_middleware
from shared.services.embedding import get_embedding_model
from shared.services.reranker import get_reranker
from shared.services.vectorstore import get_vectorstore
from chat.routers.webhook import router as webhook_router

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Chat API starting — warming models...")
    get_embedding_model()
    get_vectorstore()
    get_reranker()
    logger.info("Chat API ready")
    yield
    logger.info("Chat API shutting down")


app = FastAPI(title="CU TIP RAG — Chat API", version=APP_VERSION, lifespan=lifespan)
setup_middleware(app)
app.include_router(webhook_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "chat", "version": APP_VERSION}
```

- [ ] **Step 5: Create chat/Dockerfile**

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

- [ ] **Step 6: Create chat/requirements.txt**

```
fastapi
uvicorn[standard]
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
pydantic-settings
google-cloud-firestore
firebase-admin
```

- [ ] **Step 7: Verify chat service starts**

```bash
cd cutip-rag-chatbot
PYTHONPATH=. uvicorn chat.main:app --port 8001 &
sleep 5
curl -s http://localhost:8001/health
# Expected: {"status":"ok","service":"chat","version":"4.1.0"}
kill %1
```

---

## Task 3: Create ingest/ service

**Files:** Create `ingest/` directory with Ingestion Worker service.

- [ ] **Step 1: Create directory structure + copy files**

```bash
mkdir -p ingest/routers ingest/services
touch ingest/__init__.py ingest/routers/__init__.py ingest/services/__init__.py
cp routers/ingestion.py ingest/routers/ingestion.py
cp services/ingestion.py ingest/services/ingestion.py
cp services/vision.py ingest/services/vision.py
cp services/gdrive.py ingest/services/gdrive.py
```

- [ ] **Step 2: Update imports in all ingest/ files**

Same pattern as chat: shared imports → `from shared.`, ingest-internal → `from ingest.services.`

Key replacements in `ingest/services/ingestion.py`:
- `from services import usage` → `from shared.services import usage`
- `from services.vectorstore import` → `from shared.services.vectorstore import`
- `from services.embedding import` → `from shared.services.embedding import`
- `from services.vision import` → `from ingest.services.vision import`
- `from services.bm25 import` → `from shared.services.bm25_cache import` (see note below)

**Note:** BM25 cache invalidation in `_upsert()` calls `from services.bm25 import invalidate_bm25_cache`. Since BM25 is a chat-only service, the ingest service only needs the invalidation function. Create a thin stub `shared/services/bm25_cache.py`:

```python
# shared/services/bm25_cache.py
"""BM25 cache invalidation stub — actual index lives in chat service."""

def invalidate_bm25_cache(namespace: str) -> None:
    """No-op in non-chat services. Chat service rebuilds on next search."""
    pass
```

Update `ingest/services/ingestion.py` to import from `shared.services.bm25_cache`.

- [ ] **Step 3: Create ingest/main.py**

```python
# ingest/main.py
"""Ingestion Worker — document processing + Pinecone upsert."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from shared.config import APP_VERSION
from shared.middleware import setup_middleware
from shared.services.embedding import get_embedding_model
from shared.services.vectorstore import get_vectorstore
from ingest.routers.ingestion import router as ingestion_router

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Ingestion Worker starting — warming embedding model...")
    get_embedding_model()
    get_vectorstore()
    logger.info("Ingestion Worker ready")
    yield
    logger.info("Ingestion Worker shutting down")


app = FastAPI(title="CU TIP RAG — Ingestion Worker", version=APP_VERSION, lifespan=lifespan)
setup_middleware(app)
app.include_router(ingestion_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ingest", "version": APP_VERSION}
```

- [ ] **Step 4: Create ingest/Dockerfile**

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-core libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY shared/ /app/shared/
COPY ingest/ /app/ingest/
COPY ingest/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "ingest.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 5: Create ingest/requirements.txt**

```
fastapi
uvicorn[standard]
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
pydantic-settings
google-cloud-firestore
firebase-admin
```

- [ ] **Step 6: Verify ingest service starts**

```bash
PYTHONPATH=. uvicorn ingest.main:app --port 8002 &
sleep 5
curl -s http://localhost:8002/health
kill %1
```

---

## Task 4: Create admin/ service

**Files:** Create `admin/` directory with Admin API service.

- [ ] **Step 1: Create directory structure + copy files**

```bash
mkdir -p admin/routers
touch admin/__init__.py admin/routers/__init__.py
cp routers/tenants.py admin/routers/tenants.py
cp routers/users.py admin/routers/users.py
cp routers/analytics.py admin/routers/analytics.py
cp routers/backup.py admin/routers/backup.py
cp routers/privacy.py admin/routers/privacy.py
cp routers/registration.py admin/routers/registration.py
```

- [ ] **Step 2: Update imports in all admin/ files**

Same pattern: shared imports → `from shared.`, no admin-internal service files (admin only uses shared services).

Key replacements:
- `from config import` → `from shared.config import`
- `from schemas import` → `from shared.schemas import`
- `from services.auth import` → `from shared.services.auth import`
- `from services import firestore` → `from shared.services import firestore`
- `from services import usage` → `from shared.services import usage`
- `from services import backup` → `from shared.services import backup`
- `from services.vectorstore import` → `from shared.services.vectorstore import`
- `from services.dependencies import` → `from shared.services.dependencies import`
- `from services.rate_limit import` → `from shared.services.rate_limit import`

- [ ] **Step 3: Create admin/main.py**

```python
# admin/main.py
"""Admin API — tenants, users, analytics, backup, privacy, registration."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from shared.config import APP_VERSION
from shared.middleware import setup_middleware
from admin.routers.tenants import router as tenants_router
from admin.routers.users import router as users_router
from admin.routers.analytics import router as analytics_router
from admin.routers.analytics import global_router as usage_router
from admin.routers.backup import router as backup_router
from admin.routers.privacy import router as privacy_router
from admin.routers.registration import router as registration_router

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Admin API starting...")
    logger.info("Admin API ready")
    yield
    logger.info("Admin API shutting down")


app = FastAPI(title="CU TIP RAG — Admin API", version=APP_VERSION, lifespan=lifespan)
setup_middleware(app)
app.include_router(tenants_router)
app.include_router(users_router)
app.include_router(analytics_router)
app.include_router(usage_router)
app.include_router(backup_router)
app.include_router(privacy_router)
app.include_router(registration_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "admin", "version": APP_VERSION}
```

- [ ] **Step 4: Create admin/Dockerfile**

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

- [ ] **Step 5: Create admin/requirements.txt**

```
fastapi
uvicorn[standard]
pinecone
httpx
slowapi
pydantic-settings
google-cloud-firestore
google-cloud-storage
firebase-admin
```

- [ ] **Step 6: Verify admin service starts**

```bash
PYTHONPATH=. uvicorn admin.main:app --port 8003 &
sleep 5
curl -s http://localhost:8003/health
kill %1
```

---

## Task 5: Create docker-compose.yml

- [ ] **Step 1: Create docker-compose.yml**

```yaml
# docker-compose.yml — Run all 3 services locally
services:
  chat:
    build:
      context: .
      dockerfile: chat/Dockerfile
    ports:
      - "8001:8000"
    env_file: .env
    environment:
      - PYTHONPATH=/app

  ingest:
    build:
      context: .
      dockerfile: ingest/Dockerfile
    ports:
      - "8002:8000"
    env_file: .env
    environment:
      - PYTHONPATH=/app

  admin:
    build:
      context: .
      dockerfile: admin/Dockerfile
    ports:
      - "8003:8000"
    env_file: .env
    environment:
      - PYTHONPATH=/app
```

---

## Task 6: Update admin-portal for split URLs

**Files:** Modify admin-portal api.ts and env files.

- [ ] **Step 1: Add NEXT_PUBLIC_INGEST_URL to env files**

In `admin-portal/.env.local`:
```
NEXT_PUBLIC_INGEST_URL=http://localhost:8002
```

In `admin-portal/.env.production` (placeholder — update after deploy):
```
NEXT_PUBLIC_INGEST_URL=https://cutip-ingest-worker-265709916451.asia-southeast1.run.app
```

- [ ] **Step 2: Update admin-portal/src/lib/api.ts**

Add ingest URL getter:
```typescript
function getIngestUrl(): string {
  if (typeof window !== "undefined") {
    return (
      localStorage.getItem("ingest_url") ||
      process.env.NEXT_PUBLIC_INGEST_URL ||
      getApiUrl()  // fallback to API URL
    );
  }
  return process.env.NEXT_PUBLIC_INGEST_URL || getApiUrl();
}
```

Create `ingestRequest` function that uses `getIngestUrl()`:
```typescript
async function ingestRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const apiUrl = getIngestUrl();
  // ... same as request() but uses ingestUrl
}
```

Update these functions to use `ingestRequest`:
- `getDocuments()` → `ingestRequest`
- `deleteDocuments()` → `ingestRequest`
- `ingestDocument()` → `ingestRequest`
- `ingestSpreadsheet()` → `ingestRequest`
- `ingestGDrive()` → `ingestRequest`
- `ingestGDriveScan()` → `ingestRequest`
- `ingestGDriveFile()` → `ingestRequest`

All other functions stay on `request()` (admin API).

- [ ] **Step 3: Verify admin-portal builds**

```bash
cd admin-portal
npx next build
```

---

## Task 7: Deploy 3 Cloud Run services

- [ ] **Step 1: Build and deploy Chat API**

```bash
cd cutip-rag-chatbot
gcloud builds submit --tag asia-southeast1-docker.pkg.dev/cutip-rag/cloud-run-source-deploy/cutip-chat-api --region=asia-southeast1 -f chat/Dockerfile .

gcloud run deploy cutip-chat-api \
  --image asia-southeast1-docker.pkg.dev/cutip-rag/cloud-run-source-deploy/cutip-chat-api \
  --region asia-southeast1 \
  --set-secrets "PINECONE_API_KEY=PINECONE_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,COHERE_API_KEY=COHERE_API_KEY:latest,ADMIN_API_KEY=ADMIN_API_KEY:latest" \
  --allow-unauthenticated --port 8000 --memory 1Gi --cpu 2
```

Verify: `curl https://cutip-chat-api-....run.app/health`

- [ ] **Step 2: Build and deploy Ingestion Worker**

```bash
gcloud builds submit --tag asia-southeast1-docker.pkg.dev/cutip-rag/cloud-run-source-deploy/cutip-ingest-worker --region=asia-southeast1 -f ingest/Dockerfile .

gcloud run deploy cutip-ingest-worker \
  --image asia-southeast1-docker.pkg.dev/cutip-rag/cloud-run-source-deploy/cutip-ingest-worker \
  --region asia-southeast1 \
  --set-secrets "PINECONE_API_KEY=PINECONE_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,COHERE_API_KEY=COHERE_API_KEY:latest,ADMIN_API_KEY=ADMIN_API_KEY:latest" \
  --allow-unauthenticated --port 8000 --memory 2Gi --cpu 2
```

Verify: `curl https://cutip-ingest-worker-....run.app/health`

- [ ] **Step 3: Build and deploy Admin API**

```bash
gcloud builds submit --tag asia-southeast1-docker.pkg.dev/cutip-rag/cloud-run-source-deploy/cutip-admin-api --region=asia-southeast1 -f admin/Dockerfile .

gcloud run deploy cutip-admin-api \
  --image asia-southeast1-docker.pkg.dev/cutip-rag/cloud-run-source-deploy/cutip-admin-api \
  --region asia-southeast1 \
  --set-secrets "PINECONE_API_KEY=PINECONE_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,COHERE_API_KEY=COHERE_API_KEY:latest,ADMIN_API_KEY=ADMIN_API_KEY:latest" \
  --allow-unauthenticated --port 8000 --memory 512Mi --cpu 1
```

Verify: `curl https://cutip-admin-api-....run.app/health`

---

## Task 8: Switch external wiring

- [ ] **Step 1: Update admin-portal .env.production with real URLs**

```
NEXT_PUBLIC_API_URL=https://cutip-admin-api-265709916451.asia-southeast1.run.app
NEXT_PUBLIC_INGEST_URL=https://cutip-ingest-worker-265709916451.asia-southeast1.run.app
```

Build and deploy admin-portal:
```bash
cd admin-portal
gcloud builds submit --tag asia-southeast1-docker.pkg.dev/cutip-rag/cloud-run-source-deploy/cutip-admin-portal --region=asia-southeast1
gcloud run deploy cutip-admin-portal --image asia-southeast1-docker.pkg.dev/cutip-rag/cloud-run-source-deploy/cutip-admin-portal --region asia-southeast1 --allow-unauthenticated --port 3000 --memory 512Mi --cpu 1
```

- [ ] **Step 2: Update LINE webhook URL**

In LINE Developers Console → Messaging API → Webhook URL:
```
https://cutip-chat-api-265709916451.asia-southeast1.run.app/webhook/line
```

- [ ] **Step 3: Update Cloud Scheduler jobs**

```bash
gcloud scheduler jobs update http cutip-01-auto-scan \
  --location=asia-southeast1 \
  --uri="https://cutip-ingest-worker-265709916451.asia-southeast1.run.app/api/tenants/cutip_01/ingest/gdrive/scan"

gcloud scheduler jobs update http cutip-backup-daily \
  --location=asia-southeast1 \
  --uri="https://cutip-admin-api-265709916451.asia-southeast1.run.app/api/backups/firestore"

gcloud scheduler jobs update http cutip-retention-cleanup \
  --location=asia-southeast1 \
  --uri="https://cutip-admin-api-265709916451.asia-southeast1.run.app/api/privacy/retention/cleanup"
```

- [ ] **Step 4: Add Cloud Monitoring uptime checks**

```bash
# Chat API health
gcloud monitoring uptime-check-configs create cutip-chat-health \
  --display-name="CU TIP Chat API Health" \
  --resource-type=uptime-url \
  --hostname=cutip-chat-api-265709916451.asia-southeast1.run.app \
  --path=/health --period=300

# Ingest Worker health
gcloud monitoring uptime-check-configs create cutip-ingest-health \
  --display-name="CU TIP Ingest Worker Health" \
  --resource-type=uptime-url \
  --hostname=cutip-ingest-worker-265709916451.asia-southeast1.run.app \
  --path=/health --period=300

# Admin API health
gcloud monitoring uptime-check-configs create cutip-admin-health \
  --display-name="CU TIP Admin API Health" \
  --resource-type=uptime-url \
  --hostname=cutip-admin-api-265709916451.asia-southeast1.run.app \
  --path=/health --period=300
```

---

## Task 9: Verify everything works

- [ ] **Step 1: Test Chat API**

```bash
# Health
curl -s https://cutip-chat-api-....run.app/health

# Send test chat
python -c "
import httpx
r = httpx.post('https://cutip-chat-api-....run.app/api/chat',
    headers={'Content-Type':'application/json','X-API-Key':'...'},
    json={'tenant_id':'cutip_01','query':'ตารางเรียน','user_id':'test'},
    timeout=60)
print(r.status_code, r.text[:200])
"
```

- [ ] **Step 2: Test Ingestion Worker**

```bash
# Health
curl -s https://cutip-ingest-worker-....run.app/health

# List documents
curl -s https://cutip-ingest-worker-....run.app/api/tenants/cutip_01/documents \
  -H "X-API-Key: ..."
```

- [ ] **Step 3: Test Admin API**

```bash
# Health
curl -s https://cutip-admin-api-....run.app/health

# List tenants
curl -s https://cutip-admin-api-....run.app/api/tenants \
  -H "X-API-Key: ..."
```

- [ ] **Step 4: Test admin-portal**

Open https://cutip-admin-portal-....run.app in browser:
- Login
- Dashboard loads (admin-api)
- Tenant detail → Documents tab loads (ingest-worker)
- Settings → connection test passes

- [ ] **Step 5: Test LINE chatbot**

Send a message in LINE and verify the bot responds.

---

## Task 10: Clean up monolith (optional, after verification)

- [ ] **Step 1: Delete old monolith Cloud Run service**

```bash
gcloud run services delete cutip-rag-bot --region asia-southeast1
```

Only do this after all verification passes and LINE webhook is confirmed working on the new chat service.
