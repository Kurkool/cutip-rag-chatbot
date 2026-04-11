from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ──────────────────────────────────────
# Tenant
# ──────────────────────────────────────

class TenantCreate(BaseModel):
    tenant_id: str = Field(..., pattern=r"^[a-z0-9_]+$", examples=["cutip_01"])
    faculty_name: str
    line_destination: str  # LINE bot user ID (destination field in webhook)
    line_channel_access_token: str
    line_channel_secret: str
    pinecone_namespace: str
    persona: str = ""  # Empty = use DEFAULT_PERSONA from agent.py
    is_active: bool = True


class TenantUpdate(BaseModel):
    faculty_name: str | None = None
    line_destination: str | None = None
    line_channel_access_token: str | None = None
    line_channel_secret: str | None = None
    pinecone_namespace: str | None = None
    persona: str | None = None
    is_active: bool | None = None


class TenantResponse(BaseModel):
    tenant_id: str
    faculty_name: str
    line_destination: str
    pinecone_namespace: str
    persona: str
    is_active: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ──────────────────────────────────────
# Ingestion
# ──────────────────────────────────────

class IngestMetadata(BaseModel):
    doc_category: str = "general"  # form, curriculum, schedule, general
    url: str = ""
    download_link: str = ""


class IngestResponse(BaseModel):
    message: str
    chunks_processed: int


class IngestMarkdownRequest(BaseModel):
    content: str
    title: str = ""
    metadata: IngestMetadata = IngestMetadata()


class IngestSpreadsheetResponse(BaseModel):
    message: str
    sheets_processed: int
    chunks_processed: int


# ──────────────────────────────────────
# Chat
# ──────────────────────────────────────

class ChatRequest(BaseModel):
    query: str
    user_id: str | None = None
    tenant_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict[str, Any]]


# ──────────────────────────────────────
# Chat Logs & Analytics
# ──────────────────────────────────────

class ChatLogEntry(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    query: str
    answer: str
    sources: list[dict[str, Any]] = []
    created_at: datetime | None = None


class AnalyticsResponse(BaseModel):
    tenant_id: str
    total_chats: int
    unique_users: int
    period_start: datetime | None = None
    period_end: datetime | None = None
