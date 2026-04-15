"""Rate limiting via slowapi.

Limits:
- Chat endpoints: per IP
- Admin API: per authenticated user (via IP fallback)
- Ingestion: per tenant (heavy operations)
- Auth: per IP (brute-force protection)
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from shared.config import settings


def _get_tenant_from_path(request: Request) -> str:
    """Extract tenant_id from URL path for per-tenant rate limiting.

    Path pattern: /api/tenants/{tenant_id}/ingest/...
    """
    parts = request.url.path.strip("/").split("/")
    # api / tenants / {tenant_id} / ...
    if len(parts) >= 3 and parts[0] == "api" and parts[1] == "tenants":
        return f"tenant:{parts[2]}"
    return get_remote_address(request)


limiter = Limiter(key_func=get_remote_address)

# Pre-configured limit strings
chat_limit = settings.RATE_LIMIT_CHAT
admin_limit = settings.RATE_LIMIT_ADMIN
ingestion_limit = settings.RATE_LIMIT_INGESTION
ingestion_key_func = _get_tenant_from_path
auth_limit = settings.RATE_LIMIT_AUTH
