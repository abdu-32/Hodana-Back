"""
API / contract-level tests against apps/showcase/urls.py + views.py.

Per Document 07 Sec 2's test pyramid, this file verifies HTTP status
codes, the shared error envelope, and authorization behavior at the
client boundary -- not business rules already covered in
test_services.py.

Endpoint mapping (apps/showcase/urls.py):
    GET  /showcase/gallery                                      -> FR-SHOWCASE-002
    GET  /showcase/hackathons/{hackathonId}                      -> FR-SHOWCASE-001
    POST /showcase/hackathons/{hackathonId}/publish               -> FR-SHOWCASE-001
    POST /showcase/hackathons/{hackathonId}/unpublish             -> FR-SHOWCASE-001/002
    PUT/DELETE /showcase/submissions/{submissionId}/visibility    -> FR-SHOWCASE-001
"""

import uuid

import pytest
from rest_framework import status

from apps.accounts.tests.factories import AccountFactory
from apps.judging.tests.factories import JudgingRoundFactory, RoundResultFactory
from apps.submissions.tests.factories import SubmissionFactory

from ..models import ShowcaseOverride

pytestmark = pytest.mark.django_db


def _closed_overall_round(hackathon):
    return JudgingRoundFactory(hackathon=hackathon, track=None, status="closed")


# ---------------------------------------------------------------------------
# GET /showcase/hackathons/{hackathonId} -- FR-SHOWCASE-001
# ---------------------------------------------------------------------------


class TestHackathonShowcaseEndpoint:
    def _url(self, hackathon):
        return f"/api/v1/showcase/hackathons/{hackathon.id}"

    def test_404s_while_unpublished(self, api_client, hackathon):
        response = api_client.get(self._url(hackathon))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_public_and_unauthenticated_once_published(self, api_client, hackathon, organizer_account, organizer_role, auth_headers):
        round = _closed_overall_round(hackathon)
        submission = SubmissionFactory(team__hackathon=hackathon)
        RoundResultFactory(round=round, submission=submission, rank=1)
        api_client.post(
            f"/api/v1/showcase/hackathons/{hackathon.id}/publish", format="json",
            **auth_headers(organizer_account),
        )

        response = api_client.get(self._url(hackathon))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["hackathonId"] == str(hackathon.id)
        assert len(response.data["overallResults"]) == 1
        assert response.data["overallResults"][0]["submission"]["id"] == str(submission.id)

    def test_unknown_hackathon_404s(self, api_client):
        response = api_client.get(f"/api/v1/showcase/hackathons/{uuid.uuid4()}")
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# POST /showcase/hackathons/{hackathonId}/publish -- FR-SHOWCASE-001
# ---------------------------------------------------------------------------


class TestPublishEndpoint:
    def _url(self, hackathon):
        return f"/api/v1/showcase/hackathons/{hackathon.id}/publish"

    def test_requires_authentication(self, api_client, hackathon):
        response = api_client.post(self._url(hackathon), format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_non_organizer_forbidden(self, api_client, hackathon, auth_headers):
        _closed_overall_round(hackathon)
        stranger = AccountFactory()
        response = api_client.post(self._url(hackathon), format="json", **auth_headers(stranger))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_organizer_publishes(self, api_client, hackathon, organizer_account, organizer_role, auth_headers):
        _closed_overall_round(hackathon)
        response = api_client.post(self._url(hackathon), format="json", **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["showcasePublishedAt"] is not None

    def test_cannot_publish_with_an_open_round(self, api_client, hackathon, organizer_account, organizer_role, auth_headers):
        JudgingRoundFactory(hackathon=hackathon, track=None, status="open")
        response = api_client.post(self._url(hackathon), format="json", **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.data


# ---------------------------------------------------------------------------
# POST /showcase/hackathons/{hackathonId}/unpublish -- FR-SHOWCASE-001/002
# ---------------------------------------------------------------------------


class TestUnpublishEndpoint:
    def _publish_url(self, hackathon):
        return f"/api/v1/showcase/hackathons/{hackathon.id}/publish"

    def _unpublish_url(self, hackathon):
        return f"/api/v1/showcase/hackathons/{hackathon.id}/unpublish"

    def test_organizer_unpublishes(self, api_client, hackathon, organizer_account, organizer_role, auth_headers):
        _closed_overall_round(hackathon)
        api_client.post(self._publish_url(hackathon), format="json", **auth_headers(organizer_account))

        response = api_client.post(self._unpublish_url(hackathon), format="json", **auth_headers(organizer_account))

        assert response.status_code == status.HTTP_200_OK
        assert response.data["showcasePublishedAt"] is None
        assert api_client.get(f"/api/v1/showcase/hackathons/{hackathon.id}").status_code == status.HTTP_404_NOT_FOUND

    def test_cannot_unpublish_when_not_published(self, api_client, hackathon, organizer_account, organizer_role, auth_headers):
        response = api_client.post(self._unpublish_url(hackathon), format="json", **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# GET /showcase/gallery -- FR-SHOWCASE-002
# ---------------------------------------------------------------------------


class TestGalleryEndpoint:
    url = "/api/v1/showcase/gallery"

    def test_public_and_unauthenticated(self, api_client, hackathon, organizer_account, organizer_role, auth_headers):
        _closed_overall_round(hackathon)
        submission = SubmissionFactory(team__hackathon=hackathon)
        api_client.post(
            f"/api/v1/showcase/hackathons/{hackathon.id}/publish", format="json", **auth_headers(organizer_account),
        )

        response = api_client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["meta"]["total"] == 1
        assert response.data["data"][0]["id"] == str(submission.id)

    def test_empty_before_anything_is_published(self, api_client):
        response = api_client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["meta"]["total"] == 0
        assert response.data["data"] == []


# ---------------------------------------------------------------------------
# PUT/DELETE /showcase/submissions/{submissionId}/visibility -- FR-SHOWCASE-001
# ---------------------------------------------------------------------------


class TestSubmissionVisibilityEndpoint:
    def _url(self, submission):
        return f"/api/v1/showcase/submissions/{submission.id}/visibility"

    def test_requires_authentication(self, api_client, hackathon):
        submission = SubmissionFactory(team__hackathon=hackathon)
        response = api_client.put(self._url(submission), {"isVisible": False, "reason": "x" * 12}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_organizer_sets_visibility(self, api_client, hackathon, organizer_account, organizer_role, auth_headers):
        submission = SubmissionFactory(team__hackathon=hackathon)
        response = api_client.put(
            self._url(submission),
            {"isVisible": False, "reason": "Hidden pending an integrity review."},
            format="json", **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["isVisible"] is False

    def test_reason_too_short_is_rejected(self, api_client, hackathon, organizer_account, organizer_role, auth_headers):
        submission = SubmissionFactory(team__hackathon=hackathon)
        response = api_client.put(
            self._url(submission), {"isVisible": False, "reason": "short"}, format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_organizer_clears_override(self, api_client, hackathon, organizer_account, organizer_role, auth_headers):
        submission = SubmissionFactory(team__hackathon=hackathon)
        api_client.put(
            self._url(submission),
            {"isVisible": False, "reason": "Hidden pending an integrity review."},
            format="json", **auth_headers(organizer_account),
        )

        response = api_client.delete(self._url(submission), **auth_headers(organizer_account))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not ShowcaseOverride.objects.filter(submission=submission).exists()