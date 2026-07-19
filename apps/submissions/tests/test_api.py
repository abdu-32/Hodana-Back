"""
API / contract-level tests against apps/submissions/urls.py + views.py.

Level, per Document 07 Sec 2's test pyramid: HTTP status codes, the
shared error envelope, and authorization behavior at the boundary a real
client hits -- NOT re-proving every business rule already covered in
test_services.py. One happy path + the contract-relevant error paths per
endpoint is the target.

Endpoint mapping (none of these are in Document 04 yet -- see the
"Not yet in Doc 04/contracts/openapi.yaml" comment in views.py):
    POST /submissions/hackathons/{hackathonId}         -> FR-SUB-001
    GET  /submissions/hackathons/{hackathonId}/me       -> supporting view
    GET  /submissions/{submissionId}                    -> team/organizer view
    POST /submissions/{submissionId}/media               -> FR-SUB-002
    POST /submissions/{submissionId}/finalize             -> FR-SUB-003
    GET  /submissions/{submissionId}/history               -> FR-SUB-004
"""

import uuid

import pytest
from rest_framework import status

from apps.accounts.tests.factories import AccountFactory

from .factories import SubmissionFactory

pytestmark = pytest.mark.django_db

# ---------------------------------------------------------------------------
# POST /submissions/hackathons/{hackathonId} -- FR-SUB-001
# ---------------------------------------------------------------------------


class TestSubmissionUpsertEndpoint:
    def url_for(self, hackathon):
        return f"/api/v1/submissions/hackathons/{hackathon.id}"

    def test_requires_authentication(self, api_client, hackathon):
        response = api_client.post(self.url_for(hackathon), {"title": "My Project"}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_returns_200_with_submission_body(self, api_client, owner, hackathon, team, auth_headers):
        response = api_client.post(
            self.url_for(hackathon),
            {"title": "My Project", "description": "A cool hack.", "repoLink": "https://github.com/example/x"},
            format="json", **auth_headers(owner),
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["title"] == "My Project"
        assert body["teamId"] == str(team.id)
        assert body["isFinalized"] is False

    def test_missing_title_returns_400(self, api_client, owner, hackathon, team, auth_headers):
        response = api_client.post(self.url_for(hackathon), {}, format="json", **auth_headers(owner))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_actor_without_a_team_returns_400(self, api_client, owner, hackathon, auth_headers):
        response = api_client.post(
            self.url_for(hackathon), {"title": "My Project"}, format="json", **auth_headers(owner),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# GET /submissions/hackathons/{hackathonId}/me
# ---------------------------------------------------------------------------


class TestMySubmissionEndpoint:
    def url_for(self, hackathon):
        return f"/api/v1/submissions/hackathons/{hackathon.id}/me"

    def test_returns_404_when_no_submission_exists(self, api_client, owner, hackathon, team, auth_headers):
        response = api_client.get(self.url_for(hackathon), **auth_headers(owner))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_returns_the_teams_submission(self, api_client, owner, hackathon, team, auth_headers):
        submission = SubmissionFactory(team=team, hackathon=hackathon)
        response = api_client.get(self.url_for(hackathon), **auth_headers(owner))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(submission.id)


# ---------------------------------------------------------------------------
# GET /submissions/{submissionId}
# ---------------------------------------------------------------------------


class TestSubmissionDetailEndpoint:
    def test_team_member_can_view(self, api_client, owner, hackathon, team, auth_headers):
        submission = SubmissionFactory(team=team, hackathon=hackathon)
        response = api_client.get(f"/api/v1/submissions/{submission.id}", **auth_headers(owner))
        assert response.status_code == status.HTTP_200_OK

    def test_outsider_returns_403(self, api_client, hackathon, team, auth_headers):
        submission = SubmissionFactory(team=team, hackathon=hackathon)
        stranger = AccountFactory()
        response = api_client.get(f"/api/v1/submissions/{submission.id}", **auth_headers(stranger))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_nonexistent_submission_returns_404(self, api_client, owner, auth_headers):
        response = api_client.get(f"/api/v1/submissions/{uuid.uuid4()}", **auth_headers(owner))
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# POST /submissions/{submissionId}/media -- FR-SUB-002
# ---------------------------------------------------------------------------


class TestSubmissionMediaEndpoint:
    def test_team_member_can_attach_media(self, api_client, owner, hackathon, team, auth_headers):
        submission = SubmissionFactory(team=team, hackathon=hackathon)
        response = api_client.post(
            f"/api/v1/submissions/{submission.id}/media",
            {"attachmentUrls": ["https://example.com/a.png"]}, format="json", **auth_headers(owner),
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["attachmentUrls"] == ["https://example.com/a.png"]

    def test_more_than_5_attachments_returns_400(self, api_client, owner, hackathon, team, auth_headers):
        submission = SubmissionFactory(team=team, hackathon=hackathon)
        urls = [f"https://example.com/{i}.png" for i in range(6)]
        response = api_client.post(
            f"/api/v1/submissions/{submission.id}/media", {"attachmentUrls": urls}, format="json", **auth_headers(owner),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# POST /submissions/{submissionId}/finalize -- FR-SUB-003
# ---------------------------------------------------------------------------


class TestSubmissionFinalizeEndpoint:
    def test_finalizing_a_complete_submission_returns_200(self, api_client, owner, hackathon, team, auth_headers):
        submission = SubmissionFactory(team=team, hackathon=hackathon)
        response = api_client.post(f"/api/v1/submissions/{submission.id}/finalize", **auth_headers(owner))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["isFinalized"] is True

    def test_finalizing_incomplete_submission_returns_400(self, api_client, owner, hackathon, team, auth_headers):
        submission = SubmissionFactory(team=team, hackathon=hackathon, repo_link="", demo_video_url="")
        response = api_client.post(f"/api/v1/submissions/{submission.id}/finalize", **auth_headers(owner))
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# GET /submissions/{submissionId}/history -- FR-SUB-004
# ---------------------------------------------------------------------------


class TestSubmissionHistoryEndpoint:
    def test_team_member_can_view_history(self, api_client, owner, hackathon, team, auth_headers):
        submission = SubmissionFactory(team=team, hackathon=hackathon)
        response = api_client.get(f"/api/v1/submissions/{submission.id}/history", **auth_headers(owner))
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["submission"]["id"] == str(submission.id)
        assert response.json()["versions"] == []

    def test_outsider_returns_403(self, api_client, hackathon, team, auth_headers):
        submission = SubmissionFactory(team=team, hackathon=hackathon)
        stranger = AccountFactory()
        response = api_client.get(f"/api/v1/submissions/{submission.id}/history", **auth_headers(stranger))
        assert response.status_code == status.HTTP_403_FORBIDDEN