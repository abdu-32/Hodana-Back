"""
API / contract-level tests against apps/organizations/urls.py + views.py.

Level, per Document 07 Sec 2's test pyramid: "API / contract -- views.py
and serializers.py via the DRF test client against Document 04's
contract. Verifies HTTP status codes, the shared error envelope (Document
03 Sec 6.5), and authorization behavior (Sec 8) at the boundary a real
client hits." That's the job of this file -- NOT re-proving every
business rule already covered in test_services.py. One happy path + the
contract-relevant error paths per endpoint is the target; exhaustive rule
branches (auto-verify domain matching, document-count limits, etc.) stay
in test_services.py.

Endpoint mapping (none of these are in Document 04 yet -- see the
"Not yet in Doc 04; add it" comments in views.py):
    POST /organizations                              -> FR-ORG-001
    GET  /organizations/{id}                          -> FR-ORG-002
    POST /organizations/{id}/verification-documents   -> FR-ORG-003
    POST /organizations/{id}/verification-review      -> FR-ORG-003
"""

import uuid

import pytest
from rest_framework import status

pytestmark = pytest.mark.django_db

# ---------------------------------------------------------------------------
# POST /organizations -- FR-ORG-001
# ---------------------------------------------------------------------------


class TestOrganizationListCreateEndpoint:
    url = "/api/v1/organizations/"

    def test_requires_authentication(self, api_client):
        response = api_client.post(self.url, {"name": "Org", "type": "company", "contactEmail": "c@example.com"}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_returns_201_with_organization_body(self, api_client, verified_account, auth_headers):
        response = api_client.post(
            self.url,
            {"name": "Some Org", "type": "company", "contactEmail": "c@example.com"},
            format="json",
            **auth_headers(verified_account),
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        # Contract shape is camelCase, not a raw model dump.
        assert body["name"] == "Some Org"
        assert body["contactEmail"] == "c@example.com"
        assert body["verificationStatus"] == "unverified"
        assert body["primaryEmailDomain"] is None

    def test_unverified_actor_returns_403(self, api_client, unverified_account, auth_headers):
        response = api_client.post(
            self.url,
            {"name": "Some Org", "type": "company", "contactEmail": "c@example.com"},
            format="json",
            **auth_headers(unverified_account),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_missing_required_field_returns_400_validation_envelope(self, api_client, verified_account, auth_headers):
        response = api_client.post(
            self.url, {"type": "company", "contactEmail": "c@example.com"}, format="json",
            **auth_headers(verified_account),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert "name" in error["details"]

    def test_invalid_type_choice_returns_400(self, api_client, verified_account, auth_headers):
        response = api_client.post(
            self.url,
            {"name": "Some Org", "type": "not-a-real-type", "contactEmail": "c@example.com"},
            format="json",
            **auth_headers(verified_account),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# GET /organizations/{id} -- FR-ORG-002
# ---------------------------------------------------------------------------


class TestOrganizationDetailEndpoint:
    def test_reachable_without_auth(self, api_client, organization):
        response = api_client.get(f"/api/v1/organizations/{organization.id}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["id"] == str(organization.id)
        assert body["verificationStatus"] == organization.verification_status

    def test_verified_badge_fields_are_present_on_a_verified_org(self, api_client, verified_organization):
        response = api_client.get(f"/api/v1/organizations/{verified_organization.id}")
        body = response.json()
        assert body["verificationStatus"] == "verified"
        assert body["verifiedAt"] is not None

    def test_nonexistent_id_returns_404(self, api_client):
        response = api_client.get(f"/api/v1/organizations/{uuid.uuid4()}")
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# POST /organizations/{id}/verification-documents -- FR-ORG-003
# ---------------------------------------------------------------------------


class TestVerificationDocumentsEndpoint:
    def url_for(self, organization):
        return f"/api/v1/organizations/{organization.id}/verification-documents"

    def test_requires_authentication(self, api_client, organization):
        response = api_client.post(
            self.url_for(organization), {"fileUrls": ["https://storage.example.com/a.pdf"]}, format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_organizer_gets_201_with_document_list(self, api_client, verified_account, organization, organizer_role, auth_headers):
        response = api_client.post(
            self.url_for(organization),
            {"fileUrls": ["https://storage.example.com/a.pdf"]},
            format="json",
            **auth_headers(verified_account),
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert len(body) == 1
        assert body[0]["fileUrl"] == "https://storage.example.com/a.pdf"

    def test_non_organizer_returns_403(self, api_client, verified_account, organization, auth_headers):
        # no organizer_role fixture -- verified_account has no
        # RoleAssignment for this org.
        response = api_client.post(
            self.url_for(organization),
            {"fileUrls": ["https://storage.example.com/a.pdf"]},
            format="json",
            **auth_headers(verified_account),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_empty_file_urls_returns_400(self, api_client, verified_account, organization, organizer_role, auth_headers):
        response = api_client.post(
            self.url_for(organization), {"fileUrls": []}, format="json", **auth_headers(verified_account),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.parametrize("bad_url", [
        "http://storage.example.com/a.pdf",  # not https
        "javascript:alert(1)",
        "https://169.254.169.254/latest/meta-data/",
        "https://localhost/a.pdf",
    ])
    def test_unsafe_file_url_returns_400(
        self, api_client, verified_account, organization, organizer_role, auth_headers, bad_url,
    ):
        response = api_client.post(
            self.url_for(organization), {"fileUrls": [bad_url]}, format="json", **auth_headers(verified_account),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# POST /organizations/{id}/verification-review -- FR-ORG-003
# ---------------------------------------------------------------------------


class TestVerificationReviewEndpoint:
    def url_for(self, organization):
        return f"/api/v1/organizations/{organization.id}/verification-review"

    def test_requires_authentication(self, api_client, pending_organization):
        response = api_client.post(self.url_for(pending_organization), {"decision": "approved"}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_non_admin_returns_403(self, api_client, verified_account, pending_organization, auth_headers):
        response = api_client.post(
            self.url_for(pending_organization), {"decision": "approved"}, format="json",
            **auth_headers(verified_account),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_platform_admin_approval_returns_200(self, api_client, platform_admin, pending_organization, auth_headers, mailoutbox):
        response = api_client.post(
            self.url_for(pending_organization), {"decision": "approved"}, format="json",
            **auth_headers(platform_admin),
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["decision"] == "approved"

    def test_rejection_without_reason_returns_400(self, api_client, platform_admin, pending_organization, auth_headers):
        response = api_client.post(
            self.url_for(pending_organization), {"decision": "rejected"}, format="json",
            **auth_headers(platform_admin),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "rejectionReason" in response.json()["error"]["details"]

    def test_rejection_with_reason_returns_200(self, api_client, platform_admin, pending_organization, auth_headers, mailoutbox):
        response = api_client.post(
            self.url_for(pending_organization),
            {"decision": "rejected", "rejectionReason": "Documents were illegible."},
            format="json",
            **auth_headers(platform_admin),
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["rejectionReason"] == "Documents were illegible."