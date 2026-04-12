"""Shared helpers used across routers and services."""

import os
from typing import Any

from fastapi import HTTPException, UploadFile

from config import settings
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


def fix_filename(filename: str) -> str:
    """Fix Thai filenames garbled by Windows curl (TIS-620 → Latin-1 mojibake).

    curl on Windows sends Thai filenames in system encoding (CP874/TIS-620),
    but FastAPI reads them as Latin-1, producing mojibake like 'ÊÍºâ¤Ã§...'
    This function detects and repairs the encoding.
    """
    try:
        # Check if the filename contains Latin-1 chars that look like TIS-620 mojibake
        raw = filename.encode("latin-1")
        decoded = raw.decode("tis-620")
        # If decoding succeeds and produces Thai chars, it was mojibake
        if any("\u0e00" <= c <= "\u0e7f" for c in decoded):
            return decoded
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass
    return filename


# ──────────────────────────────────────
# File upload validation
# ──────────────────────────────────────

async def validate_upload(file: UploadFile, allowed_extensions: set[str]) -> bytes:
    """Validate file size and extension, return file bytes."""
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    file_bytes = await file.read()

    if len(file_bytes) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    filename = fix_filename(file.filename or "unknown")
    ext = parse_file_extension(filename)
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format. Allowed: {', '.join(sorted(allowed_extensions))}",
        )

    return file_bytes


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
