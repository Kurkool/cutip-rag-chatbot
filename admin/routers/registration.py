"""Self-service registration, approval/rejection, and onboarding progress.

Registration creates a *disabled* Firebase Auth user immediately so:
- The real Firebase UID is known at approval time (fixes UID mismatch bug).
- We never persist the plaintext password — Firebase Auth stores it hashed.
- On approval we just flip the disabled flag + write the Firestore admin doc
  keyed by the real UID.
"""

import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from firebase_admin import auth as firebase_auth

from shared.schemas import RegistrationRequest, RejectRequest, OnboardingUpdate
from shared.services import firestore as firestore_service
from shared.services.auth import (
    _init_firebase,
    get_accessible_tenant,
    get_current_user,
    require_super_admin,
)
from shared.services.rate_limit import auth_limit, limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Registration / Onboarding"])


# ──────────────────────────────────────
# Self-Service Registration (public)
# ──────────────────────────────────────

@router.post("/auth/register", status_code=201)
@limiter.limit(auth_limit)
async def register(request: Request, body: RegistrationRequest):
    """Public endpoint — faculty admin registers for a new tenant."""
    _init_firebase()
    try:
        user = firebase_auth.create_user(
            email=body.email,
            password=body.password,
            display_name=body.faculty_name,
            disabled=True,
        )
    except firebase_auth.EmailAlreadyExistsError:
        raise HTTPException(status_code=409, detail="Email already registered")
    except ValueError as exc:
        # Firebase rejects malformed email / weak password with ValueError
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Firebase user creation failed for %s", body.email)
        raise HTTPException(status_code=500, detail="Registration failed")

    data = {
        "faculty_name": body.faculty_name,
        "email": body.email,
        "firebase_uid": user.uid,
        "note": body.note,
    }
    result = await firestore_service.create_registration(data)
    return result


# ──────────────────────────────────────
# List Pending Registrations (Super Admin)
# ──────────────────────────────────────

@router.get("/registrations")
async def list_registrations(
    current_user: dict[str, Any] = Depends(require_super_admin),
):
    return await firestore_service.list_registrations("pending")


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

    tenant_id = re.sub(r"[^a-z0-9]", "_", reg["faculty_name"].lower().strip())
    tenant_id = re.sub(r"_+", "_", tenant_id).strip("_")[:64]

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

    uid = reg.get("firebase_uid")
    if not uid:
        # Legacy registration without a pre-created Firebase user — reject so
        # the admin re-runs the new flow rather than creating a broken account.
        raise HTTPException(
            status_code=400,
            detail="Registration missing firebase_uid; ask user to re-register",
        )

    user_data = {
        "email": reg["email"],
        "display_name": reg["faculty_name"],
        "role": "faculty_admin",
        "tenant_ids": [tenant_id],
        "is_active": True,
    }
    await firestore_service.create_admin_user(uid, user_data)

    _init_firebase()
    try:
        firebase_auth.update_user(uid, disabled=False)
    except Exception:
        logger.exception("Failed to enable Firebase user %s on approval", uid)
        # Continue — admin doc is created; super admin can manually enable in Firebase console.

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

    uid = reg.get("firebase_uid")
    if uid:
        _init_firebase()
        try:
            firebase_auth.delete_user(uid)
        except Exception:
            logger.warning("Failed to delete Firebase user %s on reject", uid, exc_info=True)

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
