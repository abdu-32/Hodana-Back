"""
API / contract-level tests against apps/analytics/urls.py + views.py.

Level, per Document 07 Sec 2's test pyramid: verifies HTTP status codes,
the shared error envelope (Design Spec Sec 6.5), the camelCase contract
shape, and authorization behavior at the boundary a real client hits --
NOT re-proving the aggregation math already covered in test_services.py
(bucketing, rate calculation, BR-011 privacy-floor branch coverage, etc.
stay there). One happy path + the contract-relevant error paths per
endpoint is the target.

Endpoint mapping:
    GET /analytics/hackathons/{hackathonId}/dashboard      -> FR-ANALYTICS-001
    GET /analytics/hackathons/{hackathonId}/demographics   -> FR-ANALYTICS-002
"""

import uuid

import pytest
from rest_framework import status

from apps.accounts.tests.factories import AccountFactory
from apps.registrations.tests.factories import RegistrationFactory

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# GET /analytics/hackathons/{hackathonId}/dashboard -- FR-ANALYTICS-001
# ---------------------------------------------------------------------------


class TestRegistrationDashboardEndpoint:
    def url_for(self, hackathon):
        return f"/api/v1/analytics/hackathons/{hackathon.id}/dashboard"

    def test_requires_authentication(self, api_client, hackathon):
        response = api_client.get(self.url_for(hackathon))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_organizer_gets_200_with_camelcase_body(self, api_client, organizer_account, hackathon, auth_headers):
        RegistrationFactory(hackathon=hackathon)

        response = api_client.get(self.url_for(hackathon), **auth_headers(organizer_account))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["hackathonId"] == str(hackathon.id)
        assert body["registrationCount"] == 1
        assert len(body["registrationsOverTime"]) == 1
        assert body["registrationsOverTime"][0]["count"] == 1
        assert body["teamFormationRate"] == 0.0
        assert body["submissionConversionRate"] == 0.0

    def test_platform_admin_gets_200(self, api_client, platform_admin_account, hackathon, auth_headers):
        response = api_client.get(self.url_for(hackathon), **auth_headers(platform_admin_account))
        assert response.status_code == status.HTTP_200_OK

    def test_non_organizer_gets_403(self, api_client, hackathon, auth_headers):
        stranger = AccountFactory()
        response = api_client.get(self.url_for(hackathon), **auth_headers(stranger))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_nonexistent_hackathon_returns_404(self, api_client, organizer_account, auth_headers):
        response = api_client.get(
            f"/api/v1/analytics/hackathons/{uuid.uuid4()}/dashboard", **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# GET /analytics/hackathons/{hackathonId}/demographics -- FR-ANALYTICS-002
# ---------------------------------------------------------------------------


class TestDemographicBreakdownEndpoint:
    def url_for(self, hackathon):
        return f"/api/v1/analytics/hackathons/{hackathon.id}/demographics"

    def test_requires_authentication(self, api_client, hackathon):
        response = api_client.get(self.url_for(hackathon))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_below_cohort_floor_returns_200_with_placeholder(self, api_client, organizer_account, hackathon, auth_headers):
        for _ in range(9):
            RegistrationFactory(hackathon=hackathon)

        response = api_client.get(self.url_for(hackathon), **auth_headers(organizer_account))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["available"] is False
        assert body["currentCount"] == 9
        assert body["byUniversity"] == []
        assert body["bySkill"] == []

    def test_at_cohort_floor_returns_breakdown(self, api_client, organizer_account, hackathon, auth_headers):
        for _ in range(10):
            RegistrationFactory(
                hackathon=hackathon,
                user=AccountFactory(university="Addis Ababa University", skills=["python"]),
            )

        response = api_client.get(self.url_for(hackathon), **auth_headers(organizer_account))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["available"] is True
        assert body["currentCount"] == 10
        assert body["byUniversity"] == [{"label": "Addis Ababa University", "count": 10}]
        assert body["bySkill"] == [{"label": "python", "count": 10}]

    def test_non_organizer_gets_403(self, api_client, hackathon, auth_headers):
        stranger = AccountFactory()
        response = api_client.get(self.url_for(hackathon), **auth_headers(stranger))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_nonexistent_hackathon_returns_404(self, api_client, organizer_account, auth_headers):
        response = api_client.get(
            f"/api/v1/analytics/hackathons/{uuid.uuid4()}/demographics", **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# GET /analytics/platform-stats
# ---------------------------------------------------------------------------


class TestPlatformStatsEndpoint:
    url = "/api/v1/analytics/platform-stats"

    def test_public_access_returns_200_with_metrics(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "activeDevelopers" in body
        assert "totalRegistrations" in body
        assert "totalHackathons" in body
        assert "totalPrizeVolumeETB" in body
        assert "totalProjects" in body

