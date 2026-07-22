"""
API / contract-level tests against apps/judging/urls.py + views.py.

Level, per Document 07 Sec 2's test pyramid: "API / contract -- views.py
and serializers.py via the DRF test client against Document 04's
contract. Verifies HTTP status codes, the shared error envelope (Document
03 Sec 6.5), and authorization behavior (Sec 8) at the boundary a real
client hits." That's the job of this file -- NOT re-proving every
business rule already covered in test_services.py. One happy path + the
contract-relevant error paths per endpoint is the target; exhaustive rule
branches (round-robin fairness, aggregate-score math, etc.) stay in
test_services.py.

Endpoint mapping (apps/judging/urls.py):
    GET/POST /judging/rounds                                      -> FR-JUDGE-004
    GET/POST /judging/rounds/{roundId}/criteria                    -> FR-HACK-004 / BR-005
    GET/POST /judging/rounds/{roundId}/assignments                 -> FR-JUDGE-001
    POST     /judging/rounds/{roundId}/assignments/auto            -> FR-JUDGE-001
    DELETE   /judging/assignments/{assignmentId}                   -> FR-JUDGE-001
    POST     /judging/assignments/{assignmentId}/reassign          -> FR-JUDGE-001
    POST     /judging/rounds/{roundId}/open                        -> FR-JUDGE-004
    POST     /judging/rounds/{roundId}/close                       -> FR-JUDGE-004
    GET      /judging/rounds/{roundId}/results                     -> FR-JUDGE-003
    POST     /judging/judge/invitations                            -> FR-JUDGE-001
    POST     /judging/judge/invitations/{invitationId}/accept       -> FR-JUDGE-001
    GET      /judging/submissions/{submissionId}/scores             -> FR-JUDGE-002
    POST     /judging/submissions/{submissionId}/score               -> FR-JUDGE-002
    POST     /judging/scores/{scoreId}/reopen                       -> FR-JUDGE-002
"""

import uuid

import pytest
from django.utils import timezone
from rest_framework import status

from apps.accounts.models import RoleAssignment
from apps.accounts.tests.factories import AccountFactory
from apps.submissions.tests.factories import SubmissionFactory

from ..models import Score
from .factories import (
    JudgeInvitationFactory,
    JudgingAssignmentFactory,
    JudgingCriterionFactory,
    JudgingRoundFactory,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _judge_with_accepted_invitation(round):
    judge = AccountFactory()
    JudgeInvitationFactory(round=round, email=judge.email, status="accepted")
    return judge


def _eligible_submission(hackathon):
    return SubmissionFactory(team__hackathon=hackathon)


def _open_round_with_rubric(hackathon, *, weight=100):
    round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
    JudgingCriterionFactory(round=round, min_score=0, max_score=10, weight=weight)
    round.status = "open"
    round.opened_at = timezone.now()
    round.save(update_fields=["status", "opened_at"])
    return round


# ---------------------------------------------------------------------------
# GET/POST /judging/rounds -- FR-JUDGE-004
# ---------------------------------------------------------------------------


class TestRoundListCreateEndpoint:
    url = "/api/v1/judging/rounds"

    def test_create_requires_authentication(self, api_client, hackathon):
        response = api_client.post(self.url, {"hackathonId": str(hackathon.id)}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_organizer_can_create_round(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        response = api_client.post(
            self.url, {"hackathonId": str(hackathon.id)}, format="json", **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["hackathonId"] == str(hackathon.id)
        assert body["trackId"] is None
        assert body["status"] == "not_started"

    def test_non_organizer_returns_403(self, api_client, auth_headers, hackathon):
        outsider = AccountFactory()
        response = api_client.post(
            self.url, {"hackathonId": str(hackathon.id)}, format="json", **auth_headers(outsider),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_nonexistent_hackathon_returns_404(self, api_client, auth_headers, organizer_account):
        response = api_client.post(
            self.url, {"hackathonId": str(uuid.uuid4())}, format="json", **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_duplicate_scope_returns_409(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        JudgingRoundFactory(hackathon=hackathon, track=None)
        response = api_client.post(
            self.url, {"hackathonId": str(hackathon.id)}, format="json", **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_409_CONFLICT
        assert response.json()["error"]["code"] == "CONFLICT"

    def test_list_requires_authentication(self, api_client, hackathon):
        response = api_client.get(self.url, {"hackathonId": str(hackathon.id)})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_missing_hackathon_id_returns_400(self, api_client, auth_headers, organizer_account):
        response = api_client.get(self.url, **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_organizer_lists_rounds(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        response = api_client.get(
            self.url, {"hackathonId": str(hackathon.id)}, **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == str(round.id)

    def test_non_organizer_non_sponsor_returns_403(self, api_client, auth_headers, hackathon):
        JudgingRoundFactory(hackathon=hackathon)
        outsider = AccountFactory()
        response = api_client.get(
            self.url, {"hackathonId": str(hackathon.id)}, **auth_headers(outsider),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# GET/POST /judging/rounds/{roundId}/criteria -- FR-HACK-004 / BR-005
# ---------------------------------------------------------------------------


class TestCriterionListCreateEndpoint:
    def url_for(self, round):
        return f"/api/v1/judging/rounds/{round.id}/criteria"

    def test_requires_authentication(self, api_client, round):
        response = api_client.post(self.url_for(round), {"name": "Innovation", "maxScore": 10, "weight": 100}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_manager_can_create_returns_201(self, api_client, auth_headers, organizer_account, organizer_role, round):
        response = api_client.post(
            self.url_for(round),
            {"name": "Innovation", "maxScore": 10, "weight": 100},
            format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["name"] == "Innovation"
        assert body["maxScore"] == 10
        assert body["weight"] == "100.00"

    def test_non_manager_returns_403(self, api_client, auth_headers, round):
        outsider = AccountFactory()
        response = api_client.post(
            self.url_for(round),
            {"name": "Innovation", "maxScore": 10, "weight": 100},
            format="json",
            **auth_headers(outsider),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_after_round_open_returns_409(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        response = api_client.post(
            self.url_for(round),
            {"name": "Innovation", "maxScore": 10, "weight": 100},
            format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_invalid_max_score_returns_400_validation_envelope(self, api_client, auth_headers, organizer_account, organizer_role, round):
        response = api_client.post(
            self.url_for(round),
            {"name": "Innovation", "minScore": 5, "maxScore": 5, "weight": 100},
            format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"

    def test_manager_can_list_criteria(self, api_client, auth_headers, organizer_account, organizer_role, round):
        criterion = JudgingCriterionFactory(round=round)
        response = api_client.get(self.url_for(round), **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == str(criterion.id)


# ---------------------------------------------------------------------------
# POST /judging/judge/invitations -- FR-JUDGE-001
# ---------------------------------------------------------------------------


class TestJudgeInvitationCreateEndpoint:
    url = "/api/v1/judging/judge/invitations"

    def test_requires_authentication(self, api_client, round):
        response = api_client.post(self.url, {"email": "judge@example.com", "roundId": str(round.id)}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_manager_can_invite_returns_201(self, api_client, auth_headers, organizer_account, organizer_role, round):
        response = api_client.post(
            self.url, {"email": "Judge@Example.com", "roundId": str(round.id)}, format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["email"] == "judge@example.com"
        assert body["status"] == "sent"

    def test_non_manager_returns_403(self, api_client, auth_headers, round):
        outsider = AccountFactory()
        response = api_client.post(
            self.url, {"email": "judge@example.com", "roundId": str(round.id)}, format="json",
            **auth_headers(outsider),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_invite_after_round_opened_returns_400(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        response = api_client.post(
            self.url, {"email": "judge@example.com", "roundId": str(round.id)}, format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# POST /judging/judge/invitations/{invitationId}/accept -- FR-JUDGE-001
# ---------------------------------------------------------------------------


class TestJudgeInvitationAcceptEndpoint:
    def url_for(self, invitation):
        return f"/api/v1/judging/judge/invitations/{invitation.id}/accept"

    def test_requires_authentication(self, api_client, round):
        invitation = JudgeInvitationFactory(round=round, status="sent")
        response = api_client.post(self.url_for(invitation))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_invitee_can_accept_returns_200(self, api_client, auth_headers, round):
        judge = AccountFactory()
        invitation = JudgeInvitationFactory(round=round, email=judge.email, status="sent")

        response = api_client.post(self.url_for(invitation), **auth_headers(judge))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "accepted"
        assert RoleAssignment.objects.filter(
            user=judge, role="judge", scope_type="hackathon", scope_id=round.hackathon_id,
        ).exists()

    def test_invitation_for_someone_else_returns_403(self, api_client, auth_headers, round):
        invitation = JudgeInvitationFactory(round=round, status="sent")
        outsider = AccountFactory()
        response = api_client.post(self.url_for(invitation), **auth_headers(outsider))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_already_accepted_returns_409(self, api_client, auth_headers, round):
        judge = AccountFactory()
        invitation = JudgeInvitationFactory(round=round, email=judge.email, status="accepted")
        response = api_client.post(self.url_for(invitation), **auth_headers(judge))
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_nonexistent_invitation_returns_404(self, api_client, auth_headers, organizer_account):
        response = api_client.post(
            f"/api/v1/judging/judge/invitations/{uuid.uuid4()}/accept", **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# GET/POST /judging/rounds/{roundId}/assignments -- FR-JUDGE-001
# ---------------------------------------------------------------------------


class TestAssignmentListCreateEndpoint:
    def url_for(self, round):
        return f"/api/v1/judging/rounds/{round.id}/assignments"

    def test_requires_authentication(self, api_client, round):
        response = api_client.post(self.url_for(round), {}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_organizer_can_assign_returns_201(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        judge = _judge_with_accepted_invitation(round)
        submission = _eligible_submission(hackathon)

        response = api_client.post(
            self.url_for(round),
            {"submissionId": str(submission.id), "judgeUserId": str(judge.id)},
            format="json",
            **auth_headers(organizer_account),
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["submissionId"] == str(submission.id)
        assert body["judgeUserId"] == str(judge.id)

    def test_non_organizer_returns_403(self, api_client, auth_headers, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        judge = _judge_with_accepted_invitation(round)
        submission = _eligible_submission(hackathon)
        outsider = AccountFactory()

        response = api_client.post(
            self.url_for(round),
            {"submissionId": str(submission.id), "judgeUserId": str(judge.id)},
            format="json",
            **auth_headers(outsider),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_after_round_opened_returns_400(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        judge = _judge_with_accepted_invitation(round)
        submission = _eligible_submission(hackathon)

        response = api_client.post(
            self.url_for(round),
            {"submissionId": str(submission.id), "judgeUserId": str(judge.id)},
            format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_judge_without_invitation_returns_400(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        judge = AccountFactory()  # no accepted invitation
        submission = _eligible_submission(hackathon)

        response = api_client.post(
            self.url_for(round),
            {"submissionId": str(submission.id), "judgeUserId": str(judge.id)},
            format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_organizer_lists_all_assignments(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        assignment = JudgingAssignmentFactory(round=round)

        response = api_client.get(self.url_for(round), **auth_headers(organizer_account))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == str(assignment.id)

    def test_judge_lists_own_assignments(self, api_client, auth_headers, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        assignment = JudgingAssignmentFactory(round=round, judge_user=judge)
        JudgingAssignmentFactory(round=round)  # someone else's assignment

        response = api_client.get(
            self.url_for(round), {"judgeUserId": str(judge.id)}, **auth_headers(judge),
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == str(assignment.id)

    def test_judge_requesting_someone_elses_assignments_returns_403(self, api_client, auth_headers, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        other_judge = AccountFactory()
        JudgingAssignmentFactory(round=round, judge_user=other_judge)
        outsider = AccountFactory()

        response = api_client.get(
            self.url_for(round), {"judgeUserId": str(other_judge.id)}, **auth_headers(outsider),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN


# ---------------------------------------------------------------------------
# POST /judging/rounds/{roundId}/assignments/auto -- FR-JUDGE-001
# ---------------------------------------------------------------------------


class TestAutoDistributionEndpoint:
    def url_for(self, round):
        return f"/api/v1/judging/rounds/{round.id}/assignments/auto"

    def test_requires_authentication(self, api_client, round):
        response = api_client.post(self.url_for(round), {"judgeUserIds": []}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_organizer_can_auto_distribute_returns_201(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        judge = _judge_with_accepted_invitation(round)
        _eligible_submission(hackathon)

        response = api_client.post(
            self.url_for(round), {"judgeUserIds": [str(judge.id)]}, format="json",
            **auth_headers(organizer_account),
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert len(body) == 1
        assert body[0]["judgeUserId"] == str(judge.id)

    def test_non_organizer_returns_403(self, api_client, auth_headers, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        judge = _judge_with_accepted_invitation(round)
        outsider = AccountFactory()

        response = api_client.post(
            self.url_for(round), {"judgeUserIds": [str(judge.id)]}, format="json",
            **auth_headers(outsider),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unknown_judge_returns_400(self, api_client, auth_headers, organizer_account, organizer_role, round):
        response = api_client.post(
            self.url_for(round), {"judgeUserIds": [str(uuid.uuid4())]}, format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# DELETE /judging/assignments/{assignmentId} -- FR-JUDGE-001
# ---------------------------------------------------------------------------


class TestAssignmentDeleteEndpoint:
    def url_for(self, assignment):
        return f"/api/v1/judging/assignments/{assignment.id}"

    def test_requires_authentication(self, api_client, round):
        assignment = JudgingAssignmentFactory(round=round)
        response = api_client.delete(self.url_for(assignment))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_organizer_can_remove_returns_204(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        assignment = JudgingAssignmentFactory(round=round)

        response = api_client.delete(self.url_for(assignment), **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_non_organizer_returns_403(self, api_client, auth_headers, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        assignment = JudgingAssignmentFactory(round=round)
        outsider = AccountFactory()

        response = api_client.delete(self.url_for(assignment), **auth_headers(outsider))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_after_round_opened_returns_400(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        assignment = JudgingAssignmentFactory(round=round)

        response = api_client.delete(self.url_for(assignment), **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_existing_scores_without_confirm_returns_409(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        assignment = JudgingAssignmentFactory(round=round)
        criterion = JudgingCriterionFactory(round=round)
        Score.objects.create(
            submission=assignment.submission, judge_user=assignment.judge_user, criterion=criterion,
            score_value=5, status="final", finalized_at=timezone.now(),
        )

        response = api_client.delete(self.url_for(assignment), **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_existing_scores_with_confirm_returns_204(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        assignment = JudgingAssignmentFactory(round=round)
        criterion = JudgingCriterionFactory(round=round)
        Score.objects.create(
            submission=assignment.submission, judge_user=assignment.judge_user, criterion=criterion,
            score_value=5, status="final", finalized_at=timezone.now(),
        )

        response = api_client.delete(
            self.url_for(assignment), {"confirmScoreDiscard": True}, format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_nonexistent_assignment_returns_404(self, api_client, auth_headers, organizer_account):
        response = api_client.delete(
            f"/api/v1/judging/assignments/{uuid.uuid4()}", **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# POST /judging/assignments/{assignmentId}/reassign -- FR-JUDGE-001
# ---------------------------------------------------------------------------


class TestAssignmentReassignEndpoint:
    def url_for(self, assignment):
        return f"/api/v1/judging/assignments/{assignment.id}/reassign"

    def test_requires_authentication(self, api_client, round):
        assignment = JudgingAssignmentFactory(round=round)
        response = api_client.post(self.url_for(assignment), {}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_organizer_can_reassign_returns_200(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        assignment = JudgingAssignmentFactory(round=round)
        new_judge = _judge_with_accepted_invitation(round)

        response = api_client.post(
            self.url_for(assignment), {"newJudgeUserId": str(new_judge.id)}, format="json",
            **auth_headers(organizer_account),
        )

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["judgeUserId"] == str(new_judge.id)
        assert body["reassignedFromUserId"] == str(assignment.judge_user_id)

    def test_non_organizer_returns_403(self, api_client, auth_headers, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        assignment = JudgingAssignmentFactory(round=round)
        new_judge = _judge_with_accepted_invitation(round)
        outsider = AccountFactory()

        response = api_client.post(
            self.url_for(assignment), {"newJudgeUserId": str(new_judge.id)}, format="json",
            **auth_headers(outsider),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_new_judge_without_invitation_returns_400(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        assignment = JudgingAssignmentFactory(round=round)
        new_judge = AccountFactory()  # no accepted invitation

        response = api_client.post(
            self.url_for(assignment), {"newJudgeUserId": str(new_judge.id)}, format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_nonexistent_assignment_returns_404(self, api_client, auth_headers, organizer_account):
        response = api_client.post(
            f"/api/v1/judging/assignments/{uuid.uuid4()}/reassign",
            {"newJudgeUserId": str(uuid.uuid4())}, format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# POST /judging/rounds/{roundId}/open -- FR-JUDGE-004
# ---------------------------------------------------------------------------


class TestRoundOpenEndpoint:
    def url_for(self, round):
        return f"/api/v1/judging/rounds/{round.id}/open"

    def test_requires_authentication(self, api_client, round):
        response = api_client.post(self.url_for(round))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_manager_can_open_returns_200(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        JudgingCriterionFactory(round=round, weight=100)

        response = api_client.post(self.url_for(round), **auth_headers(organizer_account))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "open"

    def test_non_manager_returns_403(self, api_client, auth_headers, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        JudgingCriterionFactory(round=round, weight=100)
        outsider = AccountFactory()

        response = api_client.post(self.url_for(round), **auth_headers(outsider))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_invalid_rubric_weight_returns_400(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        JudgingCriterionFactory(round=round, weight=50)

        response = api_client.post(self.url_for(round), **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_already_open_returns_400(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = _open_round_with_rubric(hackathon)

        response = api_client.post(self.url_for(round), **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# POST /judging/rounds/{roundId}/close -- FR-JUDGE-004
# ---------------------------------------------------------------------------


class TestRoundCloseEndpoint:
    def url_for(self, round):
        return f"/api/v1/judging/rounds/{round.id}/close"

    def test_requires_authentication(self, api_client, round):
        response = api_client.post(self.url_for(round))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_manager_can_close_returns_200(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = _open_round_with_rubric(hackathon)

        response = api_client.post(self.url_for(round), **auth_headers(organizer_account))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "closed"

    def test_non_manager_returns_403(self, api_client, auth_headers, hackathon):
        round = _open_round_with_rubric(hackathon)
        outsider = AccountFactory()

        response = api_client.post(self.url_for(round), **auth_headers(outsider))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_not_open_returns_400(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")

        response = api_client.post(self.url_for(round), **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---------------------------------------------------------------------------
# GET /judging/rounds/{roundId}/results -- FR-JUDGE-003
# ---------------------------------------------------------------------------


class TestRoundResultListEndpoint:
    def url_for(self, round):
        return f"/api/v1/judging/rounds/{round.id}/results"

    def test_requires_authentication(self, api_client, round):
        response = api_client.get(self.url_for(round))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_manager_gets_200(self, api_client, auth_headers, organizer_account, organizer_role, round):
        response = api_client.get(self.url_for(round), **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_non_manager_returns_403(self, api_client, auth_headers, round):
        outsider = AccountFactory()
        response = api_client.get(self.url_for(round), **auth_headers(outsider))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_nonexistent_round_returns_404(self, api_client, auth_headers, organizer_account):
        response = api_client.get(
            f"/api/v1/judging/rounds/{uuid.uuid4()}/results", **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# GET /judging/submissions/{submissionId}/scores -- FR-JUDGE-002
# ---------------------------------------------------------------------------


class TestSubmissionScoreListEndpoint:
    def url_for(self, submission):
        return f"/api/v1/judging/submissions/{submission.id}/scores"

    def test_requires_authentication(self, api_client, hackathon):
        submission = _eligible_submission(hackathon)
        response = api_client.get(self.url_for(submission))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_organizer_gets_200(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        submission = _eligible_submission(hackathon)
        response = api_client.get(self.url_for(submission), **auth_headers(organizer_account))
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_non_organizer_returns_403(self, api_client, auth_headers, hackathon):
        submission = _eligible_submission(hackathon)
        outsider = AccountFactory()
        response = api_client.get(self.url_for(submission), **auth_headers(outsider))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_nonexistent_submission_returns_404(self, api_client, auth_headers, organizer_account):
        response = api_client.get(
            f"/api/v1/judging/submissions/{uuid.uuid4()}/scores", **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# POST /judging/submissions/{submissionId}/score -- FR-JUDGE-002
# ---------------------------------------------------------------------------


class TestSubmissionScoreCreateEndpoint:
    def url_for(self, submission):
        return f"/api/v1/judging/submissions/{submission.id}/score"

    def test_requires_authentication(self, api_client, hackathon):
        submission = _eligible_submission(hackathon)
        response = api_client.post(self.url_for(submission), {}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_assigned_judge_can_submit_score_returns_201(self, api_client, auth_headers, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, min_score=0, max_score=10, weight=100)
        judge = _judge_with_accepted_invitation(round)
        submission = _eligible_submission(hackathon)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)

        response = api_client.post(
            self.url_for(submission),
            {"criterionId": str(criterion.id), "scoreValue": 8, "status": "final"},
            format="json",
            **auth_headers(judge),
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["scoreValue"] == 8
        assert body["status"] == "final"

    def test_non_assigned_judge_returns_403(self, api_client, auth_headers, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, min_score=0, max_score=10, weight=100)
        judge = _judge_with_accepted_invitation(round)
        submission = _eligible_submission(hackathon)
        # No JudgingAssignment created for this judge/submission pair.

        response = api_client.post(
            self.url_for(submission),
            {"criterionId": str(criterion.id), "scoreValue": 8, "status": "final"},
            format="json",
            **auth_headers(judge),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_score_out_of_range_returns_400_validation_envelope(self, api_client, auth_headers, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, min_score=0, max_score=10, weight=100)
        judge = _judge_with_accepted_invitation(round)
        submission = _eligible_submission(hackathon)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)

        response = api_client.post(
            self.url_for(submission),
            {"criterionId": str(criterion.id), "scoreValue": 99, "status": "final"},
            format="json",
            **auth_headers(judge),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert "scoreValue" in error["details"]

    def test_editing_a_final_score_returns_409(self, api_client, auth_headers, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, min_score=0, max_score=10, weight=100)
        judge = _judge_with_accepted_invitation(round)
        submission = _eligible_submission(hackathon)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)
        Score.objects.create(
            submission=submission, judge_user=judge, criterion=criterion,
            score_value=7, status="final", finalized_at=timezone.now(),
        )

        response = api_client.post(
            self.url_for(submission),
            {"criterionId": str(criterion.id), "scoreValue": 9, "status": "final"},
            format="json",
            **auth_headers(judge),
        )
        assert response.status_code == status.HTTP_409_CONFLICT

    def test_nonexistent_criterion_returns_404(self, api_client, auth_headers, hackathon):
        judge = AccountFactory()
        submission = _eligible_submission(hackathon)

        response = api_client.post(
            self.url_for(submission),
            {"criterionId": str(uuid.uuid4()), "scoreValue": 8, "status": "final"},
            format="json",
            **auth_headers(judge),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ---------------------------------------------------------------------------
# POST /judging/scores/{scoreId}/reopen -- FR-JUDGE-002
# ---------------------------------------------------------------------------


class TestScoreReopenEndpoint:
    def url_for(self, score):
        return f"/api/v1/judging/scores/{score.id}/reopen"

    def _final_score(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, min_score=0, max_score=10, weight=100)
        judge = AccountFactory()
        submission = _eligible_submission(hackathon)
        return Score.objects.create(
            submission=submission, judge_user=judge, criterion=criterion,
            score_value=7, status="final", finalized_at=timezone.now(),
        )

    def test_requires_authentication(self, api_client, hackathon):
        score = self._final_score(hackathon)
        response = api_client.post(self.url_for(score), {"reason": "Requested by the judge."}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_organizer_can_reopen_returns_200(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        score = self._final_score(hackathon)

        response = api_client.post(
            self.url_for(score), {"reason": "Requested by the judge."}, format="json",
            **auth_headers(organizer_account),
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "draft"

    def test_non_organizer_returns_403(self, api_client, auth_headers, hackathon):
        score = self._final_score(hackathon)
        outsider = AccountFactory()

        response = api_client.post(
            self.url_for(score), {"reason": "Requested by the judge."}, format="json",
            **auth_headers(outsider),
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_short_reason_returns_400_validation_envelope(self, api_client, auth_headers, organizer_account, organizer_role, hackathon):
        score = self._final_score(hackathon)

        response = api_client.post(
            self.url_for(score), {"reason": "short"}, format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert "reason" in error["details"]

    def test_nonexistent_score_returns_404(self, api_client, auth_headers, organizer_account):
        response = api_client.post(
            f"/api/v1/judging/scores/{uuid.uuid4()}/reopen",
            {"reason": "Requested by the judge."}, format="json",
            **auth_headers(organizer_account),
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND