"""Self-service registration, approval/rejection, and onboarding progress."""

import hashlib
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from shared.schemas import RegistrationRequest, RejectRequest, OnboardingUpdate
from shared.services import firestore as firestore_service
from shared.services.auth import get_accessible_tenant, get_current_user, require_super_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Registration / Onboarding"])


# ──────────────────────────────────────
# Self-Service Registration (public)
# ──────────────────────────────────────

@router.post("/auth/register", status_code=201)
async def register(body: RegistrationRequest):
    """Public endpoint — faculty admin registers for a new tenant."""
    data = {
        "faculty_name": body.faculty_name,
        "email": body.email,
        "password_hash": hashlib.sha256(body.password.encode()).hexdigest(),
        "note": body.note,
    }
    result = await firestore_service.create_registration(data)
    # Never return password or hash
    result.pop("password_hash", None)
    return result


# ──────────────────────────────────────
# List Pending Registrations (Super Admin)
# ──────────────────────────────────────

@router.get("/registrations")
async def list_registrations(
    current_user: dict[str, Any] = Depends(require_super_admin),
):
    regs = await firestore_service.list_registrations("pending")
    # Strip password hashes
    for r in regs:
        r.pop("password_hash", None)
    return regs


# ──────────────────────────────────────
# Approve Registration (Super Admin)
# ──────────────────────────────────────

@router.post("/registrations/{reg_id}/approve")
async def approve_registration(
    reg_id: str,
    current_user: dict[str, Any] = Depends(require_super_admin),
):
    reg = await firestore_service.get_registration(reg_id)
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")

    if reg["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Registration already {reg['status']}")

    # Generate tenant_id from faculty name
    tenant_id = re.sub(r"[^a-z0-9]", "_", reg["faculty_name"].lower().strip())
    tenant_id = re.sub(r"_+", "_", tenant_id).strip("_")[:64]

    # Create tenant
    tenant_data = {
        "tenant_id": tenant_id,
        "faculty_name": reg["faculty_name"],
        "line_destination": "",
        "line_channel_access_token": "",
        "line_channel_secret": "",
        "pinecone_namespace": tenant_id,
        "persona": "",
        "is_active": True,
        "onboarding_completed": [],
    }
    await firestore_service.create_tenant(tenant_data)

    # Create admin user (use email as UID placeholder — real Firebase user created on first login)
    uid = hashlib.sha256(reg["email"].encode()).hexdigest()[:28]
    user_data = {
        "email": reg["email"],
        "display_name": reg["faculty_name"],
        "role": "faculty_admin",
        "tenant_ids": [tenant_id],
        "is_active": True,
    }
    await firestore_service.create_admin_user(uid, user_data)

    # Mark registration as approved
    await firestore_service.update_registration(reg_id, {"status": "approved"})

    logger.info("Registration approved: %s → tenant=%s uid=%s", reg_id, tenant_id, uid)
    return {"status": "approved", "tenant_id": tenant_id, "uid": uid}


# ──────────────────────────────────────
# Reject Registration (Super Admin)
# ──────────────────────────────────────

@router.post("/registrations/{reg_id}/reject")
async def reject_registration(
    reg_id: str,
    body: RejectRequest | None = None,
    current_user: dict[str, Any] = Depends(require_super_admin),
):
    reg = await firestore_service.get_registration(reg_id)
    if not reg:
        raise HTTPException(status_code=404, detail="Registration not found")

    reason = body.reason if body else ""
    await firestore_service.update_registration(
        reg_id, {"status": "rejected", "reject_reason": reason},
    )
    logger.info("Registration rejected: %s reason=%s", reg_id, reason)
    return {"status": "rejected", "reason": reason}


# ──────────────────────────────────────
# Onboarding Progress
# ──────────────────────────────────────

@router.get("/tenants/{tenant_id}/onboarding")
async def get_onboarding(
    tenant: dict[str, Any] = Depends(get_accessible_tenant),
):
    steps = await firestore_service.get_onboarding_status(tenant["tenant_id"])
    return {"tenant_id": tenant["tenant_id"], "completed_steps": steps}


@router.put("/tenants/{tenant_id}/onboarding")
async def update_onboarding(
    body: OnboardingUpdate,
    tenant: dict[str, Any] = Depends(get_accessible_tenant),
):
    result = await firestore_service.update_onboarding_status(
        tenant["tenant_id"], body.completed_steps,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return {
        "tenant_id": tenant["tenant_id"],
        "completed_steps": result.get("onboarding_completed", []),
    }
