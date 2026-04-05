"""Tenant CRUD endpoints."""

import logging

from fastapi import APIRouter, HTTPException

from schemas import TenantCreate, TenantResponse, TenantUpdate
from services import firestore as firestore_service
from services.dependencies import get_tenant_or_404
from services.vectorstore import get_raw_index

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["Tenants"])


@router.get("", response_model=list[TenantResponse])
async def list_tenants():
    return await firestore_service.list_tenants()


@router.post("", response_model=TenantResponse, status_code=201)
async def create_tenant(body: TenantCreate):
    existing = await firestore_service.get_tenant(body.tenant_id)
    if existing:
        raise HTTPException(status_code=409, detail="Tenant already exists")
    return await firestore_service.create_tenant(body.model_dump())


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(tenant_id: str):
    return await get_tenant_or_404(tenant_id)


@router.put("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(tenant_id: str, body: TenantUpdate):
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    tenant = await firestore_service.update_tenant(tenant_id, update_data)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.delete("/{tenant_id}", status_code=204)
async def delete_tenant(tenant_id: str):
    tenant = await get_tenant_or_404(tenant_id)

    try:
        index = get_raw_index()
        index.delete(delete_all=True, namespace=tenant["pinecone_namespace"])
    except Exception:
        logger.warning(
            "Failed to delete vectors for tenant %s (namespace may be empty)",
            tenant_id,
        )

    await firestore_service.delete_tenant(tenant_id)
