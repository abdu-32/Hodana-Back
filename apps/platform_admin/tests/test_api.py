"""
API / contract-level tests against apps/platform_admin/urls.py + views.py.

Level, per Document 07 Sec 2's test pyramid: verifies HTTP status codes,
the shared error envelope (Document 03 Sec 6.5), and authorization
behavior (Sec 8) at the boundary a real client hits -- NOT re-proving
every business rule already covered in test_services.py. One happy path
+ the contract-relevant error paths per endpoint is the target.

Endpoint mapping (none of these are in Document 04 -- ADMIN has no
FR-numbered paths there at all; see contracts/README.md on why
contracts/openapi.yaml is regenerated from views.py, not hand-authored):
    GET  /admin/organizations/pending          -> FR-ADMIN-001
    POST /admin/hackathons/{id}/suspend        -> FR-ADMIN-001
    POST /admin/hackathons/{id}/reactivate     -> FR-ADMIN-001
    POST /admin/organizations/{id}/suspend     -> FR-ADMIN-001
    POST /admin/organizations/{id}/reactivate  -> FR-ADMIN-001
    POST /admin/users/{id}/suspend             -> FR-ADMIN-001
    POST /admin/users/{id}/reactivate          -> FR-ADMIN-001
    GET  /admin/search                         -> FR-ADMIN-002
"""

import uuid

import pytest
from rest_framework import status

pytestmark = pytest.mark.django_db

# ---------------------------------------------------------------------------
# GET /admin/organizations/pending -- FR-ADMIN-001
# ---------------------------------------------------------------------------


class TestPendingOrganizationsEndpoint:
    url = "/api/v1/admin/organizations/pending"

    def test_requires_authentication(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_non_admin_returns_403(self, api_client, regular_account, auth_headers):
        response = api_client.get(self.url, **auth_headers(regular_account))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_gets_pending_queue(self, api_client, platform_admin, pending_organization, verified_organization, auth_headers):
        response = api_client.get(self.url, **auth_headers(platform_admin))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        ids = [row["id"] for row in body]
        assert str(pending_organization.id) in ids
        assert str(verified_organization.id) not in ids


# ---------------------------------------------------------------------------
# POST /admin/hackathons/{id}/suspend + /reactivate -- FR-ADMIN-001
# ---------------------------------------------------------------------------


class TestSuspendHackathonEndpoint:
    def url_for(self, hackathon):
        return f"/api/v1/admin/hackathons/{hackathon.id}/suspend"

    def test_requires_authentication(self, api_client, hackathon):
        response = api_client.post(self.url_for(hackathon), {"reason": "x"}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_non_admin_returns_403(self, api_client, regular_account, hackathon, auth_headers):
        response = api_client.post(
            self.url_for(hackathon), {"reason": "x"}, format="json", **auth_headers(regular_account),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_reason_returns_400_validation_envelope(self, api_client, platform_admin, hackathon, auth_headers):
        response = api_client.post(
            self.url_for(hackathon), {}, format="json", **auth_headers(platform_admin),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert "reason" in error["details"]

    def test_admin_gets_200_with_suspended_body(self, api_client, platform_admin, hackathon, auth_headers):
        response = api_client.post(
            self.url_for(hackathon), {"reason": "Fraudulent prize claims"}, format="json", **auth_headers(platform_admin),
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["isSuspended"] is True

    def test_unknown_hackathon_returns_404(self, api_client, platform_admin, auth_headers):
        response = api_client.post(
            f"/api/v1/admin/hackathons/{uuid.uuid4()}/suspend",
            {"reason": "x"}, format="json", **auth_headers(platform_admin),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestReactivateHackathonEndpoint:
    def test_admin_gets_200_with_unsuspended_body(self, api_client, platform_admin, suspended_hackathon, auth_headers):
        response = api_client.post(
            f"/api/v1/admin/hackathons/{suspended_hackathon.id}/reactivate",
            {"reason": "Cleared"}, format="json", **auth_headers(platform_admin),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["isSuspended"] is False


# ---------------------------------------------------------------------------
# POST /admin/organizations/{id}/suspend + /reactivate -- FR-ADMIN-001
# ---------------------------------------------------------------------------


class TestSuspendOrganizationEndpoint:
    def url_for(self, organization):
        return f"/api/v1/admin/organizations/{organization.id}/suspend"

    def test_non_admin_returns_403(self, api_client, regular_account, organization, auth_headers):
        response = api_client.post(
            self.url_for(organization), {"reason": "x"}, format="json", **auth_headers(regular_account),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_gets_200_with_suspended_body(self, api_client, platform_admin, organization, auth_headers):
        response = api_client.post(
            self.url_for(organization), {"reason": "Fake documents"}, format="json", **auth_headers(platform_admin),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["isSuspended"] is True


class TestReactivateOrganizationEndpoint:
    def test_admin_gets_200_with_unsuspended_body(self, api_client, platform_admin, suspended_organization, auth_headers):
        response = api_client.post(
            f"/api/v1/admin/organizations/{suspended_organization.id}/reactivate",
            {"reason": "Appeal accepted"}, format="json", **auth_headers(platform_admin),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["isSuspended"] is False


# ---------------------------------------------------------------------------
# POST /admin/users/{id}/suspend + /reactivate -- FR-ADMIN-001
# ---------------------------------------------------------------------------


class TestSuspendAccountEndpoint:
    def url_for(self, account):
        return f"/api/v1/admin/users/{account.id}/suspend"

    def test_non_admin_returns_403(self, api_client, regular_account, auth_headers):
        response = api_client.post(
            self.url_for(regular_account), {"reason": "x"}, format="json", **auth_headers(regular_account),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_admin_gets_200_with_suspended_body(self, api_client, platform_admin, regular_account, auth_headers):
        response = api_client.post(
            self.url_for(regular_account), {"reason": "Harassment reports"}, format="json", **auth_headers(platform_admin),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["isSuspended"] is True

    def test_admin_cannot_suspend_self_returns_400(self, api_client, platform_admin, auth_headers):
        response = api_client.post(
            self.url_for(platform_admin), {"reason": "x"}, format="json", **auth_headers(platform_admin),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_suspended_account_loses_api_access(self, api_client, platform_admin, regular_account, auth_headers):
        """FR-ADMIN-001 + NFR-SEC-005: an existing token for the suspended
        account must stop working immediately, not just future logins."""
        headers = auth_headers(regular_account)  # captured before suspension

        api_client.post(
            self.url_for(regular_account), {"reason": "x"}, format="json", **auth_headers(platform_admin),
        )

        response = api_client.get("/api/v1/admin/organizations/pending", **headers)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestReactivateAccountEndpoint:
    def test_admin_gets_200_with_unsuspended_body(self, api_client, platform_admin, regular_account, auth_headers):
        api_client.post(
            f"/api/v1/admin/users/{regular_account.id}/suspend",
            {"reason": "x"}, format="json", **auth_headers(platform_admin),
        )
        response = api_client.post(
            f"/api/v1/admin/users/{regular_account.id}/reactivate",
            {"reason": "Appeal accepted"}, format="json", **auth_headers(platform_admin),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["isSuspended"] is False


# ---------------------------------------------------------------------------
# GET /admin/search -- FR-ADMIN-002
# ---------------------------------------------------------------------------


class TestPlatformSearchEndpoint:
    url = "/api/v1/admin/search"

    def test_requires_authentication(self, api_client):
        response = api_client.get(self.url, {"q": "anything"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_non_admin_returns_403(self, api_client, regular_account, auth_headers):
        response = api_client.get(self.url, {"q": "anything"}, **auth_headers(regular_account))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_query_returns_400(self, api_client, platform_admin, auth_headers):
        response = api_client.get(self.url, **auth_headers(platform_admin))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_admin_finds_matching_records_across_all_three_types(
        self, api_client, platform_admin, regular_account, organization, hackathon, auth_headers,
    ):
        response = api_client.get(self.url, {"q": regular_account.full_name}, **auth_headers(platform_admin))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "users" in body and "organizations" in body and "hackathons" in body
        assert any(row["id"] == str(regular_account.id) for row in body["users"])
