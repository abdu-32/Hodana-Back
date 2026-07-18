"""
API / contract-level tests against apps/registrations/urls.py + views.py.

Level, per Document 07 Sec 2's test pyramid: "API / contract -- views.py
and serializers.py via the DRF test client against Document 04's
contract. Verifies HTTP status codes, the shared error envelope (Document
03 Sec 6.5), and authorization behavior (Sec 8) at the boundary a real
client hits." That's the job of this file -- NOT re-proving every
business rule already covered in test_services.py (deadline math,
eligibility branch coverage, etc. stay there). One happy path + the
contract-relevant error paths per endpoint is the target.

Endpoint mapping (none of these are in Document 04 yet -- see the
"Not yet in Doc 04; add it" comment in views.py):
    POST /registrations/hackathons/{hackathonId}           -> FR-REG-001
    POST /registrations/hackathons/{hackathonId}/withdraw  -> FR-REG-002
    GET  /registrations/me                                 -> FR-REG-003
"""

import uuid

import pytest
from rest_framework import status

from apps.hackathons.tests.factories import HackathonFactory
from apps.accounts.tests.factories import AccountFactory
from apps.organizations.tests.factories import VerifiedOrganizationFactory
from apps.registrations.tests.factories import RegistrationFactory

pytestmark = pytest.mark.django_db

# ---------------------------------------------------------------------------
# POST /registrations/hackathons/{hackathonId} -- FR-REG-001
# ---------------------------------------------------------------------------


class TestHackathonRegistrationEndpoint:
    def url_for(self, hackathon):
        return f"/api/v1/registrations/hackathons/{hackathon.id}"

    def test_requires_authentication(self, api_client, published_hackathon):
        response = api_client.post(self.url_for(published_hackathon), {}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_returns_201_with_registration_body(self, api_client, participant, published_hackathon, auth_headers, mailoutbox):
        response = api_client.post(
            self.url_for(published_hackathon),
            {"eligibilityConfirmed": True, "customAnswers": {"dietary": "vegetarian"}},
            format="json",
            **auth_headers(participant),
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        # Contract shape is camelCase, not a raw model dump.
        assert body["hackathonId"] == str(published_hackathon.id)
        assert body["userId"] == str(participant.id)
        assert body["eligibilityConfirmed"] is True
        assert body["customAnswers"] == {"dietary": "vegetarian"}
        assert body["status"] == "registered"
        assert body["withdrawnAt"] is None
        assert len(mailoutbox) == 1

    def test_omitted_optional_fields_still_returns_201(self, api_client, participant, published_hackathon, auth_headers):
        response = api_client.post(self.url_for(published_hackathon), {}, format="json", **auth_headers(participant))

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["eligibilityConfirmed"] is False
        assert body["customAnswers"] is None

    def test_duplicate_registration_returns_409(self, api_client, participant, published_hackathon, auth_headers):
        api_client.post(self.url_for(published_hackathon), {}, format="json", **auth_headers(participant))

        response = api_client.post(self.url_for(published_hackathon), {}, format="json", **auth_headers(participant))

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_draft_hackathon_returns_400_validation_envelope(self, api_client, participant, auth_headers):
        
        draft_hackathon = HackathonFactory(status="draft")
        response = api_client.post(
            self.url_for(draft_hackathon), {}, format="json", **auth_headers(participant),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_nonexistent_hackathon_returns_404(self, api_client, participant, auth_headers):
        response = api_client.post(
            f"/api/v1/registrations/hackathons/{uuid.uuid4()}", {}, format="json", **auth_headers(participant),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_institution_restriction_failure_returns_400_with_rule_name(self, api_client, auth_headers, published_hackathon):
        
        allowed_org = VerifiedOrganizationFactory(primary_email_domain="aau.edu.et")
        published_hackathon.eligibility_rules = {"institution_restriction": [str(allowed_org.id)]}
        published_hackathon.save(update_fields=["eligibility_rules"])

        outsider = AccountFactory(email="student@othercollege.edu")
        response = api_client.post(
            self.url_for(published_hackathon), {}, format="json", **auth_headers(outsider),
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["error"]["details"]["eligibility"]["rule"] == "institution_restriction"


# ---------------------------------------------------------------------------
# POST /registrations/hackathons/{hackathonId}/withdraw -- FR-REG-002
# ---------------------------------------------------------------------------


class TestHackathonRegistrationWithdrawEndpoint:
    def url_for(self, hackathon):
        return f"/api/v1/registrations/hackathons/{hackathon.id}/withdraw"

    def test_requires_authentication(self, api_client, registration):
        response = api_client.post(self.url_for(registration.hackathon), format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_returns_200_with_withdrawn_status(self, api_client, participant, registration, auth_headers):
        response = api_client.post(
            self.url_for(registration.hackathon), format="json", **auth_headers(participant),
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["status"] == "withdrawn"
        assert body["withdrawnAt"] is not None

    def test_no_registration_for_that_hackathon_returns_404(self, api_client, participant, published_hackathon, auth_headers):
        response = api_client.post(
            self.url_for(published_hackathon), format="json", **auth_headers(participant),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_withdrawing_twice_returns_400(self, api_client, participant, registration, auth_headers):
        api_client.post(self.url_for(registration.hackathon), format="json", **auth_headers(participant))

        response = api_client.post(
            self.url_for(registration.hackathon), format="json", **auth_headers(participant),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_another_users_registration_is_not_reachable(self, api_client, registration, auth_headers):
        """FR-REG-003's strict-scoping principle applies to withdrawal too
        -- another user has no row to withdraw, so this is a 404, not a
        403 that would confirm the registration's existence to them."""
        
        other_user = AccountFactory()
        response = api_client.post(
            self.url_for(registration.hackathon), format="json", **auth_headers(other_user),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# GET /registrations/me -- FR-REG-003
# ---------------------------------------------------------------------------


class TestMyRegistrationsEndpoint:
    url = "/api/v1/registrations/me"

    def test_requires_authentication(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_returns_200_with_only_requesters_registrations(self, api_client, participant, registration, auth_headers):
        
        RegistrationFactory(user=AccountFactory())  # someone else's -- must not leak in

        response = api_client.get(self.url, **auth_headers(participant))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["id"] == str(registration.id)

    def test_returns_empty_data_for_user_with_no_registrations(self, api_client, auth_headers):
        
        lonely_user = AccountFactory()
        response = api_client.get(self.url, **auth_headers(lonely_user))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["data"] == []