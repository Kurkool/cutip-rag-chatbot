"""Chat API — LINE webhook + /api/chat endpoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from shared.config import APP_VERSION
from shared.middleware import setup_middleware
from shared.services.embedding import get_embedding_model
from shared.services.vectorstore import get_vectorstore
from chat.services.reranker import get_reranker
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
