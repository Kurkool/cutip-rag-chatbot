"""PDPA compliance endpoints — data export, deletion, anonymization,
retention cleanup, consent tracking, and privacy policy."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from typing import Any

from shared.config import settings
from shared.schemas import ConsentRequest, RetentionCleanupRequest
from shared.services import firestore as firestore_service
from shared.services.auth import (
    get_accessible_tenant,
    get_current_user,
    require_super_admin,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Privacy / PDPA"])


# ──────────────────────────────────────
# Data Export
# ──────────────────────────────────────

@router.get("/tenants/{tenant_id}/privacy/export/{user_id}")
async def export_user_data(
    user_id: str,
    tenant: dict[str, Any] = Depends(get_accessible_tenant),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    logger.info(
        "PDPA export: admin=%s tenant=%s user=%s",
        current_user.get("uid"), tenant["tenant_id"], user_id,
    )
    data = await firestore_service.export_user_data(tenant["tenant_id"], user_id)
    return data


# ──────────────────────────────────────
# Data Deletion (Right to be Forgotten)
# ──────────────────────────────────────

@router.delete("/tenants/{tenant_id}/privacy/users/{user_id}")
async def delete_user_data(
    user_id: str,
    tenant: dict[str, Any] = Depends(get_accessible_tenant),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    logger.info(
        "PDPA delete: admin=%s tenant=%s user=%s",
        current_user.get("uid"), tenant["tenant_id"], user_id,
    )
    result = await firestore_service.delete_user_data(tenant["tenant_id"], user_id)
    return result


# ──────────────────────────────────────
# Data Anonymization
# ──────────────────────────────────────

@router.post("/tenants/{tenant_id}/privacy/anonymize/{user_id}")
async def anonymize_user_data(
    user_id: str,
    tenant: dict[str, Any] = Depends(get_accessible_tenant),
    current_user: dict[str, Any] = Depends(get_current_user),
):
    logger.info(
        "PDPA anonymize: admin=%s tenant=%s user=%s",
        current_user.get("uid"), tenant["tenant_id"], user_id,
    )
    result = await firestore_service.anonymize_user_data(tenant["tenant_id"], user_id)
    return result


# ──────────────────────────────────────
# Retention Cleanup
# ──────────────────────────────────────

@router.post("/privacy/retention/cleanup")
async def retention_cleanup(
    body: RetentionCleanupRequest | None = None,
    current_user: dict[str, Any] = Depends(require_super_admin),
):
    days = (body.retention_days if body and body.retention_days else None) or settings.RETENTION_DAYS
    logger.info(
        "PDPA retention cleanup: admin=%s retention_days=%d",
        current_user.get("uid"), days,
    )
    result = await firestore_service.cleanup_expired_data(days)
    return result


# ──────────────────────────────────────
# Consent Tracking
# ──────────────────────────────────────

@router.post("/tenants/{tenant_id}/privacy/consents", status_code=201)
async def record_consent(
    body: ConsentRequest,
    tenant: dict[str, Any] = Depends(get_accessible_tenant),
):
    result = await firestore_service.record_consent(
        tenant["tenant_id"], body.user_id, body.consent_type, body.version,
    )
    return result


@router.get("/tenants/{tenant_id}/privacy/consents/{user_id}")
async def get_user_consents(
    user_id: str,
    tenant: dict[str, Any] = Depends(get_accessible_tenant),
):
    return await firestore_service.get_user_consents(tenant["tenant_id"], user_id)


@router.delete("/tenants/{tenant_id}/privacy/consents/{user_id}/{consent_type}")
async def revoke_consent(
    user_id: str,
    consent_type: str,
    tenant: dict[str, Any] = Depends(get_accessible_tenant),
):
    revoked = await firestore_service.revoke_consent(tenant["tenant_id"], user_id, consent_type)
    if not revoked:
        raise HTTPException(status_code=404, detail="Consent not found")
    return {"revoked": True}


# ──────────────────────────────────────
# Privacy Policy (public)
# ──────────────────────────────────────

@router.get("/privacy/policy")
async def get_privacy_policy():
    return {
        "data_collected": [
            "LINE user ID (pseudonymous identifier)",
            "Chat messages (questions and answers)",
            "Conversation history (up to 5 turns, 30-minute TTL)",
        ],
        "retention_days": settings.RETENTION_DAYS,
        "purpose": "To provide AI-powered academic assistance to university students",
        "user_rights": [
            "Right to access/export your data",
            "Right to delete your data (right to be forgotten)",
            "Right to data anonymization",
            "Right to withdraw consent",
        ],
        "contact": "Data Protection Officer — via university faculty admin",
    }
