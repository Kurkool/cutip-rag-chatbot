"""Tenant CRUD endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from shared.schemas import GDriveConnectRequest, TenantCreate, TenantResponse, TenantUpdate
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

    # If namespace is being changed, bump bm25_invalidate_ts so chat-api
    # rewarms its BM25 cache from the new namespace on the next query.
    # Without this, chat keeps serving results from the stale cache until
    # the container cycles.
    if (
        "pinecone_namespace" in update_data
        and update_data["pinecone_namespace"] != tenant.get("pinecone_namespace")
    ):
        import time
        update_data["bm25_invalidate_ts"] = time.time()
        logger.info(
            "Namespace change for %s: %s → %s (bumping bm25_invalidate_ts)",
            tenant["tenant_id"], tenant.get("pinecone_namespace"),
            update_data["pinecone_namespace"],
        )

    updated = await firestore_service.update_tenant(tenant["tenant_id"], update_data)
    if not updated:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return updated


@router.post("/{tenant_id}/gdrive/connect", response_model=TenantResponse)
async def connect_gdrive(
    body: GDriveConnectRequest,
    tenant: dict = Depends(get_accessible_tenant),
):
    """Save the Drive folder selected via the admin-portal Picker flow.

    The frontend has already (1) obtained the user's OAuth token, (2) shown
    the Google Picker, (3) called Drive API ``files.permissions.create`` to
    add the service account as Editor on the selected folder. This endpoint
    just persists the resulting folder_id + folder_name so the scheduled
    ``/api/ingest/scan-all`` + manual scans pick up the tenant's Drive.
    """
    updated = await firestore_service.update_tenant(
        tenant["tenant_id"],
        {
            "drive_folder_id": body.folder_id,
            "drive_folder_name": body.folder_name,
        },
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Tenant not found")
    logger.info(
        "GDrive connected for tenant %s: folder_id=%s name=%r",
        tenant["tenant_id"], body.folder_id, body.folder_name,
    )
    return updated


@router.delete("/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: str,
    _admin: dict = Depends(require_super_admin),
):
    """Delete a tenant, its vectors, and all linked per-tenant records.

    Cascade: Pinecone vectors + chat_logs + conversations + consents +
    admin_user.tenant_ids stripped. Leaving orphaned records would keep
    PDPA subject data alive after a tenant is removed.
    """
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

    counts = await firestore_service.delete_tenant_cascade(tenant_id)
    logger.info("Tenant %s cascade-deleted: %s", tenant_id, counts)
