"""Firebase Authentication + Role-Based Access Control.

Supports two auth methods:
1. Firebase ID token (Bearer) — for admin portal users
2. API key (X-API-Key) — for Cloud Scheduler / programmatic access

Roles:
- super_admin: full access to all tenants and user management
- faculty_admin: access only to assigned tenants
"""

import hmac
import logging
from functools import lru_cache
from typing import Any

import firebase_admin
from firebase_admin import auth as firebase_auth, credentials
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from shared.config import settings
from shared.services import firestore as firestore_service

logger = logging.getLogger(__name__)

# ──────────────────────────────────────
# Firebase Admin SDK
# ──────────────────────────────────────

_bearer = HTTPBearer(auto_error=False)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


@lru_cache()
def _init_firebase() -> firebase_admin.App:
    """Initialize Firebase Admin SDK (singleton, uses GCP default credentials)."""
    try:
        return firebase_admin.get_app()
    except ValueError:
        cred = credentials.ApplicationDefault()
        return firebase_admin.initialize_app(cred, {
            "projectId": settings.FIREBASE_PROJECT_ID,
        })


def _verify_id_token(token: str) -> dict[str, Any]:
    """Verify a Firebase ID token and return decoded claims.

    Raises:
        HTTPException(401): If token is invalid, expired, or verification fails.
    """
    _init_firebase()
    try:
        return firebase_auth.verify_id_token(token)
    except firebase_auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid authentication token")
    except firebase_auth.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="Authentication token expired")
    except Exception:
        logger.exception("Firebase token verification failed")
        raise HTTPException(status_code=401, detail="Authentication failed")


# ──────────────────────────────────────
# FastAPI Dependencies
# ──────────────────────────────────────

# Synthetic user returned when authenticating via API key (Cloud Scheduler, etc.)
_SYSTEM_USER: dict[str, Any] = {
    "uid": "__api_key__",
    "email": "system@api-key",
    "display_name": "System (API Key)",
    "role": "super_admin",
    "tenant_ids": [],
    "is_active": True,
}


async def get_current_user(
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer),
    api_key: str | None = Security(_api_key_header),
) -> dict[str, Any]:
    """Authenticate via Firebase ID token or API key.

    Priority: Bearer token > API key.

    Returns:
        User dict with keys: uid, email, display_name, role, tenant_ids, is_active.

    Raises:
        HTTPException(401): No valid auth provided.
        HTTPException(403): User not registered or account disabled.
    """
    # 1. Try Bearer token (Firebase Auth)
    if bearer and bearer.credentials:
        decoded = _verify_id_token(bearer.credentials)
        uid = decoded["uid"]

        user = await firestore_service.get_admin_user(uid)
        if not user:
            raise HTTPException(
                status_code=403,
                detail="User not registered as admin. Contact super admin.",
            )
        if not user.get("is_active", False):
            raise HTTPException(status_code=403, detail="User account is disabled")
        return user

    # 2. Fallback to API key (Cloud Scheduler / programmatic).
    # Constant-time compare + require both sides non-empty to prevent
    # empty-key bypass and timing attacks.
    if api_key and settings.ADMIN_API_KEY and hmac.compare_digest(
        api_key.encode("utf-8"), settings.ADMIN_API_KEY.encode("utf-8"),
    ):
        return dict(_SYSTEM_USER)  # return a fresh dict so callers cannot mutate the singleton

    raise HTTPException(status_code=401, detail="Not authenticated")


async def require_super_admin(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Dependency that requires super_admin role.

    Raises:
        HTTPException(403): If user is not a super admin.
    """
    if current_user.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin access required")
    return current_user


def check_tenant_access(current_user: dict[str, Any], tenant_id: str) -> None:
    """Verify that the user has access to the given tenant.

    Super admins have access to all tenants. Faculty admins can only
    access tenants listed in their tenant_ids.

    Raises:
        HTTPException(403): If user does not have access.
    """
    if current_user.get("role") == "super_admin":
        return
    allowed = current_user.get("tenant_ids", [])
    if tenant_id not in allowed:
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this tenant",
        )


async def get_accessible_tenant(
    tenant_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Combined dependency: verify auth + tenant access + fetch tenant.

    Use this in any endpoint scoped to a single tenant to avoid
    repeating check_tenant_access() + get_tenant_or_404().

    Returns:
        Tenant dict from Firestore.

    Raises:
        HTTPException(401/403): Auth or access failure.
        HTTPException(404): Tenant not found.
    """
    check_tenant_access(current_user, tenant_id)
    tenant = await firestore_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant
