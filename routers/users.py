"""Admin user management endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from firebase_admin import auth as firebase_auth

from schemas import (
    AdminUserCreate,
    AdminUserResponse,
    AdminUserUpdate,
    InitAdminRequest,
)
from services import firestore as firestore_service
from services.auth import _init_firebase, get_current_user, require_super_admin
from services.rate_limit import auth_limit, limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Users"])


# ──────────────────────────────────────
# Helpers
# ──────────────────────────────────────

def _create_firebase_user(email: str, password: str, display_name: str) -> str:
    """Create a Firebase Auth user and return the UID.

    If the email already exists in the bootstrap flow, returns existing UID.
    For normal creation, raises 409.
    """
    _init_firebase()
    try:
        fb_user = firebase_auth.create_user(
            email=email, password=password, display_name=display_name,
        )
        return fb_user.uid
    except firebase_auth.EmailAlreadyExistsError:
        raise
    except Exception:
        logger.exception("Failed to create Firebase Auth user for %s", email)
        raise HTTPException(status_code=500, detail="Failed to create user")


# ──────────────────────────────────────
# Current user
# ──────────────────────────────────────

@router.get("/users/me", response_model=AdminUserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user's profile."""
    return current_user


# ──────────────────────────────────────
# Bootstrap: create first super admin
# ──────────────────────────────────────

@router.post("/auth/init", response_model=AdminUserResponse, status_code=201)
@limiter.limit(auth_limit)
async def init_first_admin(request: Request, body: InitAdminRequest):
    """Create the first super admin. Only works when no admin users exist."""
    count = await firestore_service.count_admin_users()
    if count > 0:
        raise HTTPException(
            status_code=409,
            detail="Admin users already exist. Use /api/users to manage.",
        )

    try:
        uid = _create_firebase_user(body.email, body.password, body.display_name)
    except firebase_auth.EmailAlreadyExistsError:
        fb_user = firebase_auth.get_user_by_email(body.email)
        uid = fb_user.uid

    user_data = {
        "email": body.email,
        "display_name": body.display_name,
        "role": "super_admin",
        "tenant_ids": [],
        "is_active": True,
    }
    result = await firestore_service.create_admin_user(uid, user_data)
    logger.info("First super admin created: %s (%s)", body.email, uid)
    return result


# ──────────────────────────────────────
# CRUD (Super Admin only)
# ──────────────────────────────────────

@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(_admin: dict = Depends(require_super_admin)):
    """List all admin users."""
    return await firestore_service.list_admin_users()


@router.post("/users", response_model=AdminUserResponse, status_code=201)
async def create_user(
    body: AdminUserCreate,
    _admin: dict = Depends(require_super_admin),
):
    """Create a new admin user (Firebase Auth + Firestore)."""
    # Validate tenant_ids exist
    for tid in body.tenant_ids:
        if not await firestore_service.get_tenant(tid):
            raise HTTPException(status_code=404, detail=f"Tenant '{tid}' not found")

    try:
        uid = _create_firebase_user(body.email, body.password, body.display_name)
    except firebase_auth.EmailAlreadyExistsError:
        raise HTTPException(status_code=409, detail="Email already registered")

    user_data = {
        "email": body.email,
        "display_name": body.display_name,
        "role": body.role.value,
        "tenant_ids": body.tenant_ids,
        "is_active": True,
    }
    result = await firestore_service.create_admin_user(uid, user_data)
    logger.info("Admin user created: %s (role=%s)", body.email, body.role.value)
    return result


@router.get("/users/{uid}", response_model=AdminUserResponse)
async def get_user(uid: str, _admin: dict = Depends(require_super_admin)):
    """Get a specific admin user."""
    user = await firestore_service.get_admin_user(uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/users/{uid}", response_model=AdminUserResponse)
async def update_user(
    uid: str,
    body: AdminUserUpdate,
    _admin: dict = Depends(require_super_admin),
):
    """Update an admin user's role, tenant access, or status."""
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Convert enum to string for Firestore
    if "role" in update_data and update_data["role"] is not None:
        update_data["role"] = update_data["role"].value

    # Validate tenant_ids
    if update_data.get("tenant_ids"):
        for tid in update_data["tenant_ids"]:
            if not await firestore_service.get_tenant(tid):
                raise HTTPException(status_code=404, detail=f"Tenant '{tid}' not found")

    result = await firestore_service.update_admin_user(uid, update_data)
    if not result:
        raise HTTPException(status_code=404, detail="User not found")
    return result


@router.delete("/users/{uid}", status_code=204)
async def delete_user(uid: str, current_user: dict = Depends(require_super_admin)):
    """Delete an admin user (Firestore + Firebase Auth)."""
    if current_user["uid"] == uid:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    deleted = await firestore_service.delete_admin_user(uid)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")

    _init_firebase()
    try:
        firebase_auth.delete_user(uid)
    except Exception:
        logger.warning("Could not delete Firebase Auth user %s (may not exist)", uid)
