"""Tenant CRUD endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from shared.schemas import TenantCreate, TenantResponse, TenantUpdate
from shared.services import firestore as firestore_service
from shared.services.auth import get_accessible_tenant, get_current_user, require_super_admin
from shared.services.vectorstore import get_raw_index

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["Tenants"])


@router.get("", response_model=list[TenantResponse])
async def list_tenants(current_user: dict = Depends(get_current_user)):
    """List tenants. Super admin sees all; faculty admin sees only assigned."""
    tenants = await firestore_service.list_tenants()
    if current_user.get("role") == "super_admin":
        return tenants
    allowed = set(current_user.get("tenant_ids", []))
    return [t for t in tenants if t["tenant_id"] in allowed]


@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(
    body: TenantCreate,
    _admin: dict = Depends(require_super_admin),
):
    """Create a new tenant. Super admin only."""
    existing = await firestore_service.get_tenant(body.tenant_id)
    if existing:
        raise HTTPException(status_code=409, detail="Tenant already exists")
    return await firestore_service.create_tenant(body.model_dump())


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant: dict = Depends(get_accessible_tenant)):
    """Get a single tenant's config."""
    return tenant


@router.put("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    body: TenantUpdate,
    tenant: dict = Depends(get_accessible_tenant),
):
    """Update tenant config. Faculty admin can update assigned tenants."""
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = await firestore_service.update_tenant(tenant["tenant_id"], update_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return updated


@router.delete("/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: str,
    _admin: dict = Depends(require_super_admin),
):
    """Delete a tenant and all its vectors. Super admin only."""
    tenant = await firestore_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    try:
        index = get_raw_index()
        index.delete(delete_all=True, namespace=tenant["pinecone_namespace"])
    except Exception:
        logger.warning(
            "Failed to delete vectors for tenant %s (namespace may be empty)",
            tenant_id,
        )

    await firestore_service.delete_tenant(tenant_id)
