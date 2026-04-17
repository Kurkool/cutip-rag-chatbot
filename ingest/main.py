"""Ingestion Worker — document processing + Pinecone upsert."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from shared.config import APP_VERSION
from shared.middleware import setup_middleware
from shared.services.embedding import get_embedding_model
from shared.services.vectorstore import get_vectorstore
from ingest.routers.ingestion import router as ingestion_router
from ingest.routers.scan_all import router as scan_all_router

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
app.include_router(scan_all_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ingest", "version": APP_VERSION}
