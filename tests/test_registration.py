"""TDD tests for self-service registration + approval + onboarding.

Written BEFORE implementation — all tests should FAIL initially.
"""

import pytest
from tests.conftest import super_admin_headers, faculty_admin_headers, fake_db


# ──────────────────────────────────────
# 1. Self-Service Registration
# ──────────────────────────────────────

class TestRegister:
    """POST /api/auth/register"""

    async def test_register_success(self, client):
        res = await client.post(
            "/api/auth/register",
            json={
                "faculty_name": "Faculty of Arts",
                "email": "arts@cu.ac.th",
                "password": "securepass123",
                "note": "คณะอักษรศาสตร์ จุฬาฯ",
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert data["faculty_name"] == "Faculty of Arts"
        assert data["email"] == "arts@cu.ac.th"
        assert data["status"] == "pending"
        assert "id" in data
        # Password should NOT be in response
        assert "password" not in data

    async def test_register_missing_fields(self, client):
        res = await client.post(
            "/api/auth/register",
            json={"faculty_name": "Test"},
        )
        assert res.status_code == 422

    async def test_register_short_password(self, client):
        res = await client.post(
            "/api/auth/register",
            json={
                "faculty_name": "Test",
                "email": "test@test.com",
                "password": "short",
            },
        )
        assert res.status_code == 422

    async def test_register_is_public(self, client):
        """Registration should NOT require auth."""
        res = await client.post(
            "/api/auth/register",
            json={
                "faculty_name": "Public Faculty",
                "email": "pub@test.com",
                "password": "password123",
            },
        )
        assert res.status_code == 201


# ──────────────────────────────────────
# 2. List Pending Registrations (Super Admin)
# ──────────────────────────────────────

class TestListRegistrations:
    """GET /api/registrations"""

    async def test_list_pending(self, client):
        # Register first
        await client.post(
            "/api/auth/register",
            json={
                "faculty_name": "Faculty A",
                "email": "a@test.com",
                "password": "password123",
            },
        )
        res = await client.get(
            "/api/registrations",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["status"] == "pending"

    async def test_list_requires_super_admin(self, client):
        res = await client.get(
            "/api/registrations",
            headers=faculty_admin_headers(),
        )
        assert res.status_code == 403

    async def test_list_requires_auth(self, client):
        res = await client.get("/api/registrations")
        assert res.status_code == 401


# ──────────────────────────────────────
# 3. Approve Registration
# ──────────────────────────────────────

class TestApproveRegistration:
    """POST /api/registrations/{id}/approve"""

    async def test_approve_creates_tenant_and_user(self, client):
        # Register
        reg = await client.post(
            "/api/auth/register",
            json={
                "faculty_name": "Faculty of Science",
                "email": "sci@cu.ac.th",
                "password": "password123",
            },
        )
        reg_id = reg.json()["id"]

        # Approve
        res = await client.post(
            f"/api/registrations/{reg_id}/approve",
            headers=super_admin_headers(),
        )
        assert res.status_code == 200
        data = res.json()
        assert "tenant_id" in data
        assert "uid" in data
        assert data["status"] == "approved"

    async def test_approve_nonexistent_returns_404(self, client):
        res = await client.post(
            "/api/registrations/nonexistent/approve",
            headers=super_admin_headers(),
        )
        assert res.status_code == 404

    async def test_approve_requires_super_admin(self, client):
        res = await client.post(
            "/api/registrations/reg-001/approve",
            headers=faculty_admin_headers(),
        )
        assert res.status_code == 403

    async def test_approve_requires_auth(self, client):
        res = await client.post("/api/registrations/reg-001/approve")
        assert res.status_code == 401


# ──────────────────────────────────────
# 4. Reject Registration
# ──────────────────────────────────────

class TestRejectRegistration:
    """POST /api/registrations/{id}/reject"""

    async def test_reject_success(self, client):
        # Register
        reg = await client.post(
            "/api/auth/register",
            json={
                "faculty_name": "Spam Faculty",
                "email": "spam@test.com",
                "password": "password123",
            },
        )
        reg_id = reg.json()["id"]

        # Reject
        res = await client.post(
            f"/api/registrations/{reg_id}/reject",
            headers=super_admin_headers(),
            json={"reason": "Not a real faculty"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "rejected"

    async def test_reject_nonexistent_returns_404(self, client):
        res = await client.post(
            "/api/registrations/nonexistent/reject",
            headers=super_admin_headers(),
        )
        assert res.status_code == 404


# ──────────────────────────────────────
# 5. Onboarding Status
# ──────────────────────────────────────

class TestOnboardingStatus:
    """GET/PUT /api/tenants/{tenant_id}/onboarding"""

    async def test_get_onboarding_status(self, client):
        res = await client.get(
            "/api/tenants/tenant_a/onboarding",
            headers=faculty_admin_headers(),
        )
        assert res.status_code == 200
        data = res.json()
        assert "completed_steps" in data
        assert isinstance(data["completed_steps"], list)

    async def test_update_onboarding_step(self, client):
        res = await client.put(
            "/api/tenants/tenant_a/onboarding",
            headers=faculty_admin_headers(),
            json={"completed_steps": [1, 2]},
        )
        assert res.status_code == 200
        assert 1 in res.json()["completed_steps"]
        assert 2 in res.json()["completed_steps"]

    async def test_onboarding_nonexistent_tenant(self, client):
        res = await client.get(
            "/api/tenants/nonexistent/onboarding",
            headers=super_admin_headers(),
        )
        assert res.status_code == 404

    async def test_onboarding_requires_auth(self, client):
        res = await client.get("/api/tenants/tenant_a/onboarding")
        assert res.status_code == 401
