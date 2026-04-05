"""Shared helpers used across routers and services."""

import os
from typing import Any

from fastapi import HTTPException

from services import firestore as firestore_service


# ──────────────────────────────────────
# Tenant lookup
# ──────────────────────────────────────

async def get_tenant_or_404(tenant_id: str) -> dict[str, Any]:
    """Fetch tenant config from Firestore or raise 404."""
    tenant = await firestore_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


# ──────────────────────────────────────
# File helpers
# ──────────────────────────────────────

def parse_file_extension(filename: str) -> str:
    """Extract lowercase extension including the dot, e.g. '.pdf'."""
    _, ext = os.path.splitext(filename)
    return ext.lower()


# ──────────────────────────────────────
# Conversation history
# ──────────────────────────────────────

def format_history(history: list[dict]) -> str:
    """Format conversation turns into a readable string for the LLM."""
    if not history:
        return "ไม่มีประวัติสนทนา"
    lines = []
    for turn in history:
        lines.append(f"นักศึกษา: {turn['query']}")
        lines.append(f"ผู้ช่วย: {turn['answer']}")
    return "\n".join(lines)
