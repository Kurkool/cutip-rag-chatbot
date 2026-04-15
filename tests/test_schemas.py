"""Unit tests for Pydantic schemas: validation + sanitization."""

import pytest
from pydantic import ValidationError

from shared.schemas import (
    AdminUserCreate,
    AdminUserUpdate,
    ChatRequest,
    IngestMarkdownRequest,
    IngestMetadata,
    InitAdminRequest,
    TenantCreate,
    TenantUpdate,
)


# ──────────────────────────────────────
# HTML sanitization
# ──────────────────────────────────────

class TestSanitization:
    def test_strip_script_tags_from_query(self):
        req = ChatRequest(query='hello <script>alert("xss")</script> world')
        assert "<script>" not in req.query
        assert "hello" in req.query
        assert "world" in req.query

    def test_strip_html_tags_from_query(self):
        req = ChatRequest(query="<b>bold</b> <img src=x onerror=alert(1)>")
        assert "<b>" not in req.query
        assert "<img" not in req.query
        assert "bold" in req.query

    def test_strip_script_from_persona(self):
        t = TenantCreate(
            tenant_id="test_01",
            faculty_name="Test Faculty",
            line_destination="U123",
            line_channel_access_token="tok",
            line_channel_secret="sec",
            pinecone_namespace="ns-test",
            persona='Hello <script>steal()</script>',
        )
        assert "<script>" not in t.persona

    def test_strip_html_from_faculty_name(self):
        t = TenantCreate(
            tenant_id="test_01",
            faculty_name="<b>Faculty</b>",
            line_destination="U123",
            line_channel_access_token="tok",
            line_channel_secret="sec",
            pinecone_namespace="ns-test",
        )
        assert "<b>" not in t.faculty_name
        assert "Faculty" in t.faculty_name

    def test_strip_html_from_tenant_update(self):
        u = TenantUpdate(faculty_name="<script>x</script>Clean")
        assert "<script>" not in u.faculty_name
        assert "Clean" in u.faculty_name

    def test_sanitize_display_name_create(self):
        u = AdminUserCreate(
            email="a@b.com", password="12345678",
            display_name='<img src=x onerror=alert(1)>Admin',
        )
        assert "<img" not in u.display_name
        assert "Admin" in u.display_name

    def test_sanitize_display_name_update(self):
        u = AdminUserUpdate(display_name="<script>x</script>Name")
        assert "<script>" not in u.display_name
        assert "Name" in u.display_name

    def test_sanitize_display_name_update_none(self):
        u = AdminUserUpdate(display_name=None)
        assert u.display_name is None

    def test_sanitize_init_admin(self):
        u = InitAdminRequest(
            email="a@b.com", password="12345678",
            display_name="<b>Admin</b>",
        )
        assert "<b>" not in u.display_name

    def test_sanitize_markdown_content(self):
        req = IngestMarkdownRequest(
            content='# Title\n<script>bad()</script>\nContent',
        )
        assert "<script>" not in req.content
        assert "# Title" in req.content


# ──────────────────────────────────────
# Field validation
# ──────────────────────────────────────

class TestFieldValidation:
    def test_tenant_id_pattern_valid(self):
        t = TenantCreate(
            tenant_id="my_tenant_01",
            faculty_name="Test",
            line_destination="U123",
            line_channel_access_token="tok",
            line_channel_secret="sec",
            pinecone_namespace="ns-test",
        )
        assert t.tenant_id == "my_tenant_01"

    def test_tenant_id_pattern_invalid(self):
        with pytest.raises(ValidationError):
            TenantCreate(
                tenant_id="INVALID ID!",
                faculty_name="Test",
                line_destination="U123",
                line_channel_access_token="tok",
                line_channel_secret="sec",
                pinecone_namespace="ns-test",
            )

    def test_namespace_pattern_invalid(self):
        with pytest.raises(ValidationError):
            TenantCreate(
                tenant_id="test_01",
                faculty_name="Test",
                line_destination="U123",
                line_channel_access_token="tok",
                line_channel_secret="sec",
                pinecone_namespace="INVALID NS!",
            )

    def test_query_max_length(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="x" * 2001)

    def test_query_min_length(self):
        with pytest.raises(ValidationError):
            ChatRequest(query="")

    def test_password_min_length(self):
        with pytest.raises(ValidationError):
            AdminUserCreate(
                email="a@b.com", password="short",
                display_name="Name",
            )

    def test_password_max_length(self):
        with pytest.raises(ValidationError):
            AdminUserCreate(
                email="a@b.com", password="x" * 129,
                display_name="Name",
            )

    def test_markdown_content_required(self):
        with pytest.raises(ValidationError):
            IngestMarkdownRequest(content="")

    def test_doc_category_validation(self):
        m = IngestMetadata(doc_category="curriculum")
        assert m.doc_category == "curriculum"

    def test_doc_category_invalid_defaults_general(self):
        m = IngestMetadata(doc_category="invalid_category")
        assert m.doc_category == "general"

    def test_url_max_length(self):
        with pytest.raises(ValidationError):
            IngestMetadata(url="x" * 2001)

    def test_faculty_name_max_length(self):
        with pytest.raises(ValidationError):
            TenantCreate(
                tenant_id="test_01",
                faculty_name="x" * 201,
                line_destination="U123",
                line_channel_access_token="tok",
                line_channel_secret="sec",
                pinecone_namespace="ns-test",
            )
