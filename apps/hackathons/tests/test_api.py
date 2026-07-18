"""
API / contract-level tests against apps/hackathons/urls.py + views.py.
One happy path + the contract-relevant error paths per endpoint; exhaustive
rule branches stay in test_services.py (Document 07 Sec 2's test pyramid).
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status

pytestmark = pytest.mark.django_db


class TestHackathonListCreateEndpoint:
    url = "/api/v1/hackathons/"

    def test_list_is_public(self, api_client, published_hackathon):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["meta"]["total"] == 1
        assert body["data"][0]["id"] == str(published_hackathon.id)

    def test_create_requires_authentication(self, api_client, verified_org):
        response = api_client.post(self.url, {"title": "X", "hostOrgId": str(verified_org.id)}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_returns_201(self, api_client, organizer_account, verified_org, organizer_role, auth_headers):
        now = timezone.now()
        payload = {
            "title": "EthioHacks",
            "hostOrgId": str(verified_org.id),
            "registrationOpensAt": now.isoformat(),
            "registrationClosesAt": (now + timedelta(days=7)).isoformat(),
            "submissionOpensAt": (now + timedelta(days=7)).isoformat(),
            "submissionClosesAt": (now + timedelta(days=14)).isoformat(),
        }
        response = api_client.post(self.url, payload, format="json", **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["status"] == "draft"


class TestHackathonDetailEndpoint:
    def test_draft_returns_404_to_anonymous(self, api_client, hackathon):
        response = api_client.get(f"/api/v1/hackathons/{hackathon.id}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_published_returns_200_to_anonymous(self, api_client, published_hackathon):
        response = api_client.get(f"/api/v1/hackathons/{published_hackathon.id}")
        assert response.status_code == status.HTTP_200_OK

    def test_update_requires_authentication(self, api_client, hackathon):
        response = api_client.put(f"/api/v1/hackathons/{hackathon.id}", {"title": "X"}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_organizer_can_update(self, api_client, hackathon, organizer_account, organizer_role, auth_headers):
        response = api_client.put(
            f"/api/v1/hackathons/{hackathon.id}", {"title": "Renamed"}, format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["title"] == "Renamed"


class TestChallengeTrackListCreateEndpoint:
    def test_list_is_public(self, api_client, hackathon):
        response = api_client.get(f"/api/v1/hackathons/{hackathon.id}/tracks")
        assert response.status_code == status.HTTP_200_OK

    def test_create_requires_authentication(self, api_client, hackathon, verified_org):
        response = api_client.post(
            f"/api/v1/hackathons/{hackathon.id}/tracks",
            {"sponsorOrgId": str(verified_org.id), "name": "AI Track"}, format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED