import re
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ──────────────────────────────────────
# Sanitization helper
# ──────────────────────────────────────

_SCRIPT_TAG_RE = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_dangerous_html(v: str) -> str:
    """Remove <script> tags and HTML tags from user input."""
    v = _SCRIPT_TAG_RE.sub("", v)
    v = _HTML_TAG_RE.sub("", v)
    return v.strip()


# ──────────────────────────────────────
# Auth / Users
# ──────────────────────────────────────

class UserRole(str, Enum):
    super_admin = "super_admin"
    faculty_admin = "faculty_admin"


class AdminUserCreate(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)
    role: UserRole = UserRole.faculty_admin
    tenant_ids: list[str] = Field(default=[], max_length=50)

    @field_validator("display_name")
    @classmethod
    def sanitize_display_name(cls, v: str) -> str:
        return _strip_dangerous_html(v)


class AdminUserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    role: UserRole | None = None
    tenant_ids: list[str] | None = Field(default=None, max_length=50)
    is_active: bool | None = None

    @field_validator("display_name")
    @classmethod
    def sanitize_display_name(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _strip_dangerous_html(v)


class AdminUserResponse(BaseModel):
    uid: str
    email: str
    display_name: str
    role: UserRole
    tenant_ids: list[str] = []
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


class InitAdminRequest(BaseModel):
    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(default="Super Admin", max_length=100)

    @field_validator("display_name")
    @classmethod
    def sanitize_display_name(cls, v: str) -> str:
        return _strip_dangerous_html(v)


# ──────────────────────────────────────
# Tenant
# ──────────────────────────────────────

class TenantCreate(BaseModel):
    tenant_id: str = Field(..., pattern=r"^[a-z0-9_]+$", min_length=1, max_length=64, examples=["cutip_01"])
    faculty_name: str = Field(..., min_length=1, max_length=200)
    line_destination: str = Field(..., max_length=100)
    line_channel_access_token: str = Field(..., max_length=500)
    line_channel_secret: str = Field(..., max_length=100)
    pinecone_namespace: str = Field(..., pattern=r"^[a-z0-9_-]+$", max_length=64)
    persona: str = Field(default="", max_length=5000)  # Empty = use DEFAULT_PERSONA from agent.py
    is_active: bool = True

    @field_validator("faculty_name", "persona")
    @classmethod
    def sanitize_text(cls, v: str) -> str:
        return _strip_dangerous_html(v)


class TenantUpdate(BaseModel):
    faculty_name: str | None = Field(default=None, max_length=200)
    line_destination: str | None = Field(default=None, max_length=100)
    line_channel_access_token: str | None = Field(default=None, max_length=500)
    line_channel_secret: str | None = Field(default=None, max_length=100)
    pinecone_namespace: str | None = Field(default=None, max_length=64)
    persona: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None

    @field_validator("faculty_name", "persona")
    @classmethod
    def sanitize_text(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _strip_dangerous_html(v)


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

ALLOWED_DOC_CATEGORIES = {"general", "form", "curriculum", "schedule", "announcement", "regulation"}


class IngestMetadata(BaseModel):
    doc_category: str = Field(default="general", max_length=50)
    url: str = Field(default="", max_length=2000)
    download_link: str = Field(default="", max_length=2000)

    @field_validator("doc_category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ALLOWED_DOC_CATEGORIES:
            return "general"
        return v


class IngestResponse(BaseModel):
    message: str
    chunks_processed: int


class IngestMarkdownRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=500_000)  # ~500KB text
    title: str = Field(default="", max_length=500)
    metadata: IngestMetadata = IngestMetadata()

    @field_validator("content")
    @classmethod
    def sanitize_content(cls, v: str) -> str:
        return _strip_dangerous_html(v)


class IngestSpreadsheetResponse(BaseModel):
    message: str
    sheets_processed: int
    chunks_processed: int


# ──────────────────────────────────────
# Google Drive Ingestion
# ──────────────────────────────────────

class GDriveIngestRequest(BaseModel):
    folder_id: str = Field(..., max_length=200)
    doc_category: str = Field(default="general", max_length=50)


class GDriveSingleRequest(BaseModel):
    folder_id: str = Field(..., max_length=200)
    filename: str = Field(..., max_length=500)
    doc_category: str = Field(default="general", max_length=50)


class GDriveIngestResult(BaseModel):
    total_files: int
    ingested: list[dict]
    skipped: list[dict]
    errors: list[dict]


# ──────────────────────────────────────
# Backup / Restore
# ──────────────────────────────────────

class PineconeRestoreRequest(BaseModel):
    gcs_uri: str = Field(..., max_length=2000)
    namespace: str = Field(..., pattern=r"^[a-z0-9_-]+$", max_length=64)


# ──────────────────────────────────────
# Chat
# ──────────────────────────────────────

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    user_id: str | None = Field(default=None, max_length=100)
    tenant_id: str | None = Field(default=None, max_length=64)

    @field_validator("query")
    @classmethod
    def sanitize_query(cls, v: str) -> str:
        return _strip_dangerous_html(v)


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


# ──────────────────────────────────────
# PDPA / Privacy
# ──────────────────────────────────────

class ConsentRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=100)
    consent_type: str = Field(..., min_length=1, max_length=50)
    version: str = Field(default="1.0", max_length=20)


class RetentionCleanupRequest(BaseModel):
    retention_days: int | None = Field(default=None, ge=1, le=3650)


# ──────────────────────────────────────
# Registration / Onboarding
# ──────────────────────────────────────

class RegistrationRequest(BaseModel):
    faculty_name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., max_length=254)
    password: str = Field(..., min_length=8, max_length=128)
    note: str = Field(default="", max_length=500)

    @field_validator("faculty_name")
    @classmethod
    def sanitize_faculty(cls, v: str) -> str:
        return _strip_dangerous_html(v)

    @field_validator("note")
    @classmethod
    def sanitize_note(cls, v: str) -> str:
        return _strip_dangerous_html(v)


class RejectRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class OnboardingUpdate(BaseModel):
    completed_steps: list[int] = Field(..., max_length=10)
