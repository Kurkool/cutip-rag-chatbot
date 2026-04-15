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
