"""TDD tests for PDPA compliance endpoints (privacy router).

Written BEFORE implementation — all tests should FAIL initially.
"""

import pytest
from tests.conftest import super_admin_headers, faculty_admin_headers, fake_db


# ──────────────────────────────────────
# 1. Data Export
# ──────────────────────────────────────

class TestDataExport:
    """GET /api/tenants/{tenant_id}/privacy/export/{user_id}"""

    async def test_export_returns_user_data(self, client):
        res = await client.get(
            "/api/tenants/tenant_a/privacy/export/LINE_USER_001",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["user_id"] == "LINE_USER_001"
        assert data["tenant_id"] == "tenant_a"
        assert len(data["chat_logs"]) == 2
        assert data["conversation_memory"] is not None

    async def test_export_nonexistent_user_returns_empty(self, client):
        res = await client.get(
            "/api/tenants/tenant_a/privacy/export/NOBODY",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["user_id"] == "NOBODY"
        assert len(data["chat_logs"]) == 0
        assert data["conversation_memory"] is None

    async def test_export_nonexistent_tenant_returns_404(self, client):
        res = await client.get(
            "/api/tenants/nonexistent/privacy/export/LINE_USER_001",
            headers=super_admin_headers(),
        )
        assert res.status_code == 404

    async def test_export_requires_auth(self, client):
        res = await client.get(
            "/api/tenants/tenant_a/privacy/export/LINE_USER_001",
        )
        assert res.status_code == 401

    async def test_faculty_admin_can_export_assigned_tenant(self, client):
        res = await client.get(
            "/api/tenants/tenant_a/privacy/export/LINE_USER_001",
            headers=faculty_admin_headers(),
        )
        assert res.status_code == 200


# ──────────────────────────────────────
# 2. Data Deletion (Right to be Forgotten)
# ──────────────────────────────────────

class TestDataDeletion:
    """DELETE /api/tenants/{tenant_id}/privacy/users/{user_id}"""

    async def test_delete_user_data(self, client):
        res = await client.delete(
            "/api/tenants/tenant_a/privacy/users/LINE_USER_001",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["deleted_chat_logs"] == 2
        assert data["deleted_conversations"] == 1
        assert "deleted_consents" in data

    async def test_delete_nonexistent_user_returns_zero(self, client):
        res = await client.delete(
            "/api/tenants/tenant_a/privacy/users/NOBODY",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["deleted_chat_logs"] == 0
        assert data["deleted_conversations"] == 0
        assert data["deleted_consents"] == 0

    async def test_delete_nonexistent_tenant_returns_404(self, client):
        res = await client.delete(
            "/api/tenants/nonexistent/privacy/users/LINE_USER_001",
            headers=super_admin_headers(),
        )
        assert res.status_code == 404

    async def test_delete_requires_auth(self, client):
        res = await client.delete(
            "/api/tenants/tenant_a/privacy/users/LINE_USER_001",
        )
        assert res.status_code == 401


# ──────────────────────────────────────
# 3. Data Anonymization
# ──────────────────────────────────────

class TestDataAnonymization:
    """POST /api/tenants/{tenant_id}/privacy/anonymize/{user_id}"""

    async def test_anonymize_user(self, client):
        res = await client.post(
            "/api/tenants/tenant_a/privacy/anonymize/LINE_USER_001",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        data = res.json()
        assert data["anonymized_records"] == 2
        assert data["anonymous_id"].startswith("anon_")

    async def test_anonymize_nonexistent_user_returns_zero(self, client):
        res = await client.post(
            "/api/tenants/tenant_a/privacy/anonymize/NOBODY",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        assert res.json()["anonymized_records"] == 0

    async def test_anonymize_nonexistent_tenant_returns_404(self, client):
        res = await client.post(
            "/api/tenants/nonexistent/privacy/anonymize/LINE_USER_001",
            headers=super_admin_headers(),
        )
        assert res.status_code == 404

    async def test_anonymize_requires_auth(self, client):
        res = await client.post(
            "/api/tenants/tenant_a/privacy/anonymize/LINE_USER_001",
        )
        assert res.status_code == 401


# ──────────────────────────────────────
# 4. Data Retention Cleanup
# ──────────────────────────────────────

class TestRetentionCleanup:
    """POST /api/privacy/retention/cleanup"""

    async def test_cleanup_deletes_old_data(self, client):
        res = await client.post(
            "/api/privacy/retention/cleanup",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        data = res.json()
        # The seed has 1 old record (2025-09-01), default retention 90 days
        assert data["deleted_chat_logs"] >= 1

    async def test_cleanup_with_custom_days(self, client):
        res = await client.post(
            "/api/privacy/retention/cleanup",
            headers=super_admin_headers(),
            json={"retention_days": 365},
        )
        assert res.status_code == 200

    async def test_cleanup_requires_super_admin(self, client):
        res = await client.post(
            "/api/privacy/retention/cleanup",
            headers=faculty_admin_headers(),
        )
        assert res.status_code == 403

    async def test_cleanup_rejects_zero_days(self, client):
        res = await client.post(
            "/api/privacy/retention/cleanup",
            headers=super_admin_headers(),
            json={"retention_days": 0},
        )
        assert res.status_code == 422

    async def test_cleanup_rejects_negative_days(self, client):
        res = await client.post(
            "/api/privacy/retention/cleanup",
            headers=super_admin_headers(),
            json={"retention_days": -1},
        )
        assert res.status_code == 422

    async def test_cleanup_requires_auth(self, client):
        res = await client.post("/api/privacy/retention/cleanup")
        assert res.status_code == 401


# ──────────────────────────────────────
# 5. Consent Tracking
# ──────────────────────────────────────

class TestConsentTracking:
    """POST/GET /api/tenants/{tenant_id}/privacy/consents"""

    async def test_record_consent(self, client):
        res = await client.post(
            "/api/tenants/tenant_a/privacy/consents",
            headers=super_admin_headers(),
            json={
                "user_id": "LINE_USER_001",
                "consent_type": "data_collection",
                "version": "1.0",
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["user_id"] == "LINE_USER_001"
        assert data["consent_type"] == "data_collection"

    async def test_get_user_consents(self, client):
        # Record first
        await client.post(
            "/api/tenants/tenant_a/privacy/consents",
            headers=super_admin_headers(),
            json={
                "user_id": "LINE_USER_001",
                "consent_type": "data_collection",
                "version": "1.0",
            },
        )
        # Then retrieve
        res = await client.get(
            "/api/tenants/tenant_a/privacy/consents/LINE_USER_001",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["consent_type"] == "data_collection"

    async def test_revoke_consent(self, client):
        # Record first
        await client.post(
            "/api/tenants/tenant_a/privacy/consents",
            headers=super_admin_headers(),
            json={
                "user_id": "LINE_USER_001",
                "consent_type": "data_collection",
                "version": "1.0",
            },
        )
        # Revoke
        res = await client.delete(
            "/api/tenants/tenant_a/privacy/consents/LINE_USER_001/data_collection",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        assert res.json()["revoked"] is True

    async def test_revoke_nonexistent_consent(self, client):
        res = await client.delete(
            "/api/tenants/tenant_a/privacy/consents/LINE_USER_001/nonexistent_type",
            headers=super_admin_headers(),
        )
        assert res.status_code == 404

    async def test_consent_nonexistent_tenant_returns_404(self, client):
        res = await client.post(
            "/api/tenants/nonexistent/privacy/consents",
            headers=super_admin_headers(),
            json={
                "user_id": "LINE_USER_001",
                "consent_type": "data_collection",
                "version": "1.0",
            },
        )
        assert res.status_code == 404

    async def test_consent_requires_auth(self, client):
        res = await client.post(
            "/api/tenants/tenant_a/privacy/consents",
            json={
                "user_id": "LINE_USER_001",
                "consent_type": "data_collection",
                "version": "1.0",
            },
        )
        assert res.status_code == 401


# ──────────────────────────────────────
# 6. Privacy Policy
# ──────────────────────────────────────

class TestPrivacyPolicy:
    """GET /api/privacy/policy"""

    async def test_get_privacy_policy(self, client):
        res = await client.get("/api/privacy/policy")
        assert res.status_code == 200
        data = res.json()
        assert "data_collected" in data
        assert "retention_days" in data
        assert "user_rights" in data
        assert "contact" in data

    async def test_policy_is_public(self, client):
        """Privacy policy should be accessible without auth."""
        res = await client.get("/api/privacy/policy")
        assert res.status_code == 200
