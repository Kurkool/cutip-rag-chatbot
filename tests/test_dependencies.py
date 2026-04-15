"""Unit tests for shared dependencies: file helpers, tenant lookup."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from shared.services.dependencies import fix_filename, format_history, parse_file_extension


class TestParseFileExtension:
    def test_pdf(self):
        assert parse_file_extension("doc.pdf") == ".pdf"

    def test_docx(self):
        assert parse_file_extension("file.DOCX") == ".docx"

    def test_xlsx(self):
        assert parse_file_extension("data.xlsx") == ".xlsx"

    def test_no_extension(self):
        assert parse_file_extension("noext") == ""

    def test_double_extension(self):
        assert parse_file_extension("file.tar.gz") == ".gz"

    def test_dot_file(self):
        assert parse_file_extension(".gitignore") == ""


class TestFixFilename:
    def test_normal_ascii(self):
        assert fix_filename("report.pdf") == "report.pdf"

    def test_thai_utf8_passthrough(self):
        name = "รายงาน.pdf"
        assert fix_filename(name) == name


class TestFormatHistory:
    def test_empty(self):
        assert format_history([]) == "ไม่มีประวัติสนทนา"

    def test_single_turn(self):
        result = format_history([{"query": "สวัสดี", "answer": "สวัสดีค่ะ"}])
        assert "นักศึกษา: สวัสดี" in result
        assert "ผู้ช่วย: สวัสดีค่ะ" in result

    def test_multiple_turns(self):
        history = [
            {"query": "Q1", "answer": "A1"},
            {"query": "Q2", "answer": "A2"},
        ]
        result = format_history(history)
        assert "Q1" in result
        assert "A2" in result


class TestRateLimitKeyFunc:
    def test_tenant_from_path(self):
        from shared.services.rate_limit import _get_tenant_from_path

        request = MagicMock()
        request.url.path = "/api/tenants/my_tenant/ingest/document"
        assert _get_tenant_from_path(request) == "tenant:my_tenant"

    def test_tenant_from_path_no_match(self):
        from shared.services.rate_limit import _get_tenant_from_path

        request = MagicMock()
        request.url.path = "/health"
        request.client.host = "127.0.0.1"
        # Falls back to IP
        result = _get_tenant_from_path(request)
        assert "tenant:" not in result
