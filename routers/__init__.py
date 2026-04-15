from routers.analytics import global_router as usage_router
from routers.analytics import router as analytics_router
from routers.backup import router as backup_router
from routers.ingestion import router as ingestion_router
from routers.privacy import router as privacy_router
from routers.registration import router as registration_router
from routers.tenants import router as tenants_router
from routers.users import router as users_router
from routers.webhook import router as webhook_router

__all__ = [
    "webhook_router",
    "users_router",
    "tenants_router",
    "ingestion_router",
    "analytics_router",
    "usage_router",
    "backup_router",
    "privacy_router",
    "registration_router",
]
