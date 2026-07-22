"""
Unit tests against judging/services.py directly (Design Spec Sec 3.1), per
the 80% coverage target in NFR-MAINT-001. Prefer these over HTTP-level
tests for business-rule coverage; apps/judging/tests/test_api.py only
needs to confirm routing/serialization, not every business rule below.
"""

import uuid
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import RoleAssignment
from apps.accounts.tests.factories import AccountFactory
from apps.core.models import AuditLogEntry
from apps.hackathons.tests.factories import ChallengeTrackFactory
from apps.submissions.tests.factories import SubmissionFactory, SubmissionTrackFactory

from .. import services
from ..models import JudgingAssignment, JudgingCriterion, Score
from .factories import (
    JudgeInvitationFactory, JudgingAssignmentFactory, JudgingCriterionFactory,
    JudgingRoundFactory,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _grant_organizer(user, hackathon):
    return RoleAssignment.objects.create(
        user=user, role="organizer", scope_type="organization",
        scope_id=hackathon.host_org_id,
    )


def _grant_sponsor_for_track(user, track):
    return RoleAssignment.objects.create(
        user=user, role="sponsor", scope_type="track", scope_id=track.id,
    )


def _grant_sponsor_for_org(user, track):
    return RoleAssignment.objects.create(
        user=user, role="sponsor", scope_type="organization", scope_id=track.sponsor_org_id,
    )


def _accept_invitation(round, judge):
    return JudgeInvitationFactory(round=round, email=judge.email, status="accepted")


def _open_round_with_rubric(hackathon, *, weight=100):
    round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
    JudgingCriterionFactory(round=round, min_score=0, max_score=10, weight=weight)
    round.status = "open"
    round.opened_at = timezone.now()
    round.save(update_fields=["status", "opened_at"])
    return round


# ---------------------------------------------------------------------------
# FR-JUDGE-004: judging rounds
# ---------------------------------------------------------------------------


class TestListRounds:
    def test_organizer_sees_all_rounds_for_their_hackathon(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        overall = JudgingRoundFactory(hackathon=hackathon)
        track = ChallengeTrackFactory(hackathon=hackathon)
        track_round = JudgingRoundFactory(hackathon=hackathon, track=track)

        rounds = services.list_rounds(actor=organizer_account, hackathon_id=hackathon.id)

        assert {r.id for r in rounds} == {overall.id, track_round.id}

    def test_sponsor_sees_only_their_track_rounds(self, hackathon):
        track = ChallengeTrackFactory(hackathon=hackathon)
        sponsor = AccountFactory()
        _grant_sponsor_for_track(sponsor, track)
        track_round = JudgingRoundFactory(hackathon=hackathon, track=track)

        rounds = services.list_rounds(
            actor=sponsor, hackathon_id=hackathon.id, track_id=track.id,
        )

        assert [r.id for r in rounds] == [track_round.id]

    def test_returns_empty_list_without_permission_check_when_no_rounds_exist(self, hackathon):
        stranger = AccountFactory()
        assert services.list_rounds(actor=stranger, hackathon_id=hackathon.id) == []

    def test_non_manager_cannot_view_round(self, hackathon):
        JudgingRoundFactory(hackathon=hackathon)
        with pytest.raises(PermissionDenied):
            services.list_rounds(actor=AccountFactory(), hackathon_id=hackathon.id)

    def test_sponsor_of_one_track_cannot_see_a_sibling_tracks_round(self, hackathon):
        own_track = ChallengeTrackFactory(hackathon=hackathon)
        other_track = ChallengeTrackFactory(hackathon=hackathon)
        sponsor = AccountFactory()
        _grant_sponsor_for_track(sponsor, own_track)
        JudgingRoundFactory(hackathon=hackathon, track=own_track)
        JudgingRoundFactory(hackathon=hackathon, track=other_track)

        with pytest.raises(PermissionDenied):
            services.list_rounds(actor=sponsor, hackathon_id=hackathon.id)


class TestCreateRound:
    def test_organizer_creates_the_overall_round(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = services.create_round(actor=organizer_account, hackathon_id=hackathon.id)
        assert round.track_id is None
        assert round.status == "not_started"

    def test_organizer_creates_a_track_round(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        track = ChallengeTrackFactory(hackathon=hackathon)
        round = services.create_round(
            actor=organizer_account, hackathon_id=hackathon.id, track_id=track.id,
        )
        assert round.track_id == track.id

    def test_sponsor_creates_their_own_track_round(self, hackathon):
        track = ChallengeTrackFactory(hackathon=hackathon)
        sponsor = AccountFactory()
        _grant_sponsor_for_org(sponsor, track)
        round = services.create_round(
            actor=sponsor, hackathon_id=hackathon.id, track_id=track.id,
        )
        assert round.track_id == track.id

    def test_stranger_cannot_create_a_track_round(self, hackathon):
        track = ChallengeTrackFactory(hackathon=hackathon)
        with pytest.raises(PermissionDenied):
            services.create_round(
                actor=AccountFactory(), hackathon_id=hackathon.id, track_id=track.id,
            )

    def test_non_organizer_cannot_create_the_overall_round(self, hackathon):
        with pytest.raises(PermissionDenied):
            services.create_round(actor=AccountFactory(), hackathon_id=hackathon.id)

    def test_duplicate_overall_round_is_rejected(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        services.create_round(actor=organizer_account, hackathon_id=hackathon.id)
        with pytest.raises(services.ConflictError):
            services.create_round(actor=organizer_account, hackathon_id=hackathon.id)

    def test_duplicate_track_round_is_rejected(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        track = ChallengeTrackFactory(hackathon=hackathon)
        services.create_round(actor=organizer_account, hackathon_id=hackathon.id, track_id=track.id)
        with pytest.raises(services.ConflictError):
            services.create_round(actor=organizer_account, hackathon_id=hackathon.id, track_id=track.id)

    def test_nonexistent_hackathon_raises_not_found(self, organizer_account):
        with pytest.raises(NotFound):
            services.create_round(actor=organizer_account, hackathon_id=uuid.uuid4())

    def test_track_from_a_different_hackathon_raises_not_found(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        other_track = ChallengeTrackFactory()
        with pytest.raises(NotFound):
            services.create_round(
                actor=organizer_account, hackathon_id=hackathon.id, track_id=other_track.id,
            )


class TestOpenRound:
    def test_opens_a_fully_weighted_round(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        JudgingCriterionFactory(round=round, weight=100)

        opened = services.open_round(actor=organizer_account, round_id=round.id)

        assert opened.status == "open"
        assert opened.opened_at is not None

    def test_cannot_open_a_round_with_no_criteria(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        with pytest.raises(ValidationError):
            services.open_round(actor=organizer_account, round_id=round.id)

    def test_cannot_open_a_round_whose_weights_do_not_sum_to_100(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        JudgingCriterionFactory(round=round, weight=40)
        with pytest.raises(ValidationError):
            services.open_round(actor=organizer_account, round_id=round.id)

    def test_cannot_reopen_an_already_open_round(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        JudgingCriterionFactory(round=round, weight=100)
        with pytest.raises(ValidationError):
            services.open_round(actor=organizer_account, round_id=round.id)

    def test_non_manager_cannot_open_a_round(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        JudgingCriterionFactory(round=round, weight=100)
        with pytest.raises(PermissionDenied):
            services.open_round(actor=AccountFactory(), round_id=round.id)

    def test_nonexistent_round_raises_not_found(self, organizer_account):
        with pytest.raises(NotFound):
            services.open_round(actor=organizer_account, round_id=uuid.uuid4())


class TestCloseRound:
    def test_closes_an_open_round_and_materializes_results(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        JudgingCriterionFactory(round=round, weight=100)

        closed = services.close_round(actor=organizer_account, round_id=round.id)

        assert closed.status == "closed"
        assert closed.closed_at is not None

    def test_cannot_close_a_round_that_has_not_opened(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        with pytest.raises(ValidationError):
            services.close_round(actor=organizer_account, round_id=round.id)

    def test_non_manager_cannot_close_a_round(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        with pytest.raises(PermissionDenied):
            services.close_round(actor=AccountFactory(), round_id=round.id)


# ---------------------------------------------------------------------------
# FR-HACK-004 / BR-005: rubric criteria
# ---------------------------------------------------------------------------


class TestListCriteria:
    def test_returns_criteria_ordered_by_id(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        c1 = JudgingCriterionFactory(round=round, weight=50)
        c2 = JudgingCriterionFactory(round=round, weight=50)

        criteria = list(services.list_criteria(actor=organizer_account, round_id=round.id))

        assert [c.id for c in criteria] == sorted([c1.id, c2.id])

    def test_sponsor_can_list_criteria_for_their_own_track_round(self, hackathon):
        track = ChallengeTrackFactory(hackathon=hackathon)
        sponsor = AccountFactory()
        _grant_sponsor_for_track(sponsor, track)
        round = JudgingRoundFactory(hackathon=hackathon, track=track)
        criterion = JudgingCriterionFactory(round=round, weight=100)

        criteria = list(services.list_criteria(actor=sponsor, round_id=round.id))

        assert [c.id for c in criteria] == [criterion.id]

    def test_non_manager_cannot_list_criteria(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        with pytest.raises(PermissionDenied):
            services.list_criteria(actor=AccountFactory(), round_id=round.id)

    def test_nonexistent_round_raises_not_found(self, organizer_account):
        with pytest.raises(NotFound):
            services.list_criteria(actor=organizer_account, round_id=uuid.uuid4())


class TestCreateCriterion:
    def test_creates_a_criterion_within_the_100_point_budget(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)

        criterion = services.create_criterion(
            actor=organizer_account, round_id=round.id,
            name="Innovation", min_score=0, max_score=10, weight=100,
        )

        assert criterion.name == "Innovation"
        assert JudgingCriterion.objects.filter(round=round).count() == 1

    def test_max_score_must_exceed_min_score(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        with pytest.raises(ValidationError):
            services.create_criterion(
                actor=organizer_account, round_id=round.id,
                name="Innovation", min_score=5, max_score=5, weight=100,
            )

    def test_combined_weight_cannot_exceed_100(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        JudgingCriterionFactory(round=round, weight=70)

        with pytest.raises(ValidationError):
            services.create_criterion(
                actor=organizer_account, round_id=round.id,
                name="Impact", min_score=0, max_score=10, weight=40,
            )
        # The over-budget criterion is rolled back, not left dangling.
        assert JudgingCriterion.objects.filter(round=round).count() == 1

    def test_rubric_is_immutable_once_round_is_open(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        with pytest.raises(services.ConflictError):
            services.create_criterion(
                actor=organizer_account, round_id=round.id,
                name="Innovation", min_score=0, max_score=10, weight=100,
            )

    def test_non_manager_cannot_add_criteria(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        with pytest.raises(PermissionDenied):
            services.create_criterion(
                actor=AccountFactory(), round_id=round.id,
                name="Innovation", min_score=0, max_score=10, weight=100,
            )


# ---------------------------------------------------------------------------
# FR-JUDGE-001: invitations and assignment
# ---------------------------------------------------------------------------


class TestInviteJudge:
    def test_normalizes_and_stores_the_invited_email(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)

        invitation = services.invite_judge(
            actor=organizer_account, email="  Judge@Example.COM  ", round_id=round.id,
        )

        assert invitation.email == "judge@example.com"
        assert invitation.status == "sent"

    def test_cannot_invite_once_round_has_opened(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        with pytest.raises(ValidationError):
            services.invite_judge(actor=organizer_account, email="judge@example.com", round_id=round.id)

    def test_non_manager_cannot_invite_judges(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        with pytest.raises(PermissionDenied):
            services.invite_judge(actor=AccountFactory(), email="judge@example.com", round_id=round.id)


class TestAcceptInvitation:
    def test_accepting_grants_a_judge_role_assignment_on_the_hackathon(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        invitation = JudgeInvitationFactory(round=round, email=judge.email, status="sent")

        accepted = services.accept_invitation(actor=judge, invitation_id=invitation.id)

        assert accepted.status == "accepted"
        assert accepted.responded_at is not None
        assert RoleAssignment.objects.filter(
            user=judge, role="judge", scope_type="hackathon", scope_id=hackathon.id,
        ).exists()

    def test_accepting_is_idempotent_about_the_role_assignment(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        RoleAssignment.objects.create(
            user=judge, role="judge", scope_type="hackathon", scope_id=hackathon.id,
        )
        invitation = JudgeInvitationFactory(round=round, email=judge.email, status="sent")

        services.accept_invitation(actor=judge, invitation_id=invitation.id)

        assert RoleAssignment.objects.filter(
            user=judge, role="judge", scope_type="hackathon", scope_id=hackathon.id,
        ).count() == 1

    def test_only_the_invited_email_can_accept(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        invitation = JudgeInvitationFactory(round=round, email="judge@example.com", status="sent")
        with pytest.raises(PermissionDenied):
            services.accept_invitation(actor=AccountFactory(), invitation_id=invitation.id)

    def test_an_already_accepted_invitation_cannot_be_accepted_again(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        invitation = JudgeInvitationFactory(round=round, email=judge.email, status="accepted")
        with pytest.raises(services.ConflictError):
            services.accept_invitation(actor=judge, invitation_id=invitation.id)

    def test_an_expired_invitation_cannot_be_accepted(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        invitation = JudgeInvitationFactory(round=round, email=judge.email, status="expired")
        with pytest.raises(services.ConflictError):
            services.accept_invitation(actor=judge, invitation_id=invitation.id)

    def test_nonexistent_invitation_raises_not_found(self):
        with pytest.raises(NotFound):
            services.accept_invitation(actor=AccountFactory(), invitation_id=uuid.uuid4())


class TestAssignJudge:
    def test_organizer_assigns_a_judge_to_a_submission(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)

        assignment = services.assign_judge(
            actor=organizer_account, round_id=round.id,
            submission_id=submission.id, judge_user_id=judge.id,
        )

        assert assignment.judge_user_id == judge.id
        assert assignment.submission_id == submission.id

    def test_assigns_within_a_track_round_when_opted_in(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        track = ChallengeTrackFactory(hackathon=hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, track=track)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        opt_in = SubmissionTrackFactory(track=track)

        assignment = services.assign_judge(
            actor=organizer_account, round_id=round.id,
            submission_id=opt_in.submission_id, judge_user_id=judge.id,
        )

        assert assignment.submission_id == opt_in.submission_id

    def test_cannot_assign_a_submission_that_has_not_opted_into_the_track(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        track = ChallengeTrackFactory(hackathon=hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, track=track)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)

        with pytest.raises(ValidationError):
            services.assign_judge(
                actor=organizer_account, round_id=round.id,
                submission_id=submission.id, judge_user_id=judge.id,
            )

    def test_cannot_assign_a_submission_from_a_different_hackathon(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        other_submission = SubmissionFactory()

        with pytest.raises(ValidationError):
            services.assign_judge(
                actor=organizer_account, round_id=round.id,
                submission_id=other_submission.id, judge_user_id=judge.id,
            )

    def test_cannot_assign_an_ineligible_submission(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon, eligibility_status="disqualified")

        with pytest.raises(ValidationError):
            services.assign_judge(
                actor=organizer_account, round_id=round.id,
                submission_id=submission.id, judge_user_id=judge.id,
            )

    def test_judge_must_have_accepted_an_invitation_first(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        submission = SubmissionFactory(team__hackathon=hackathon)

        with pytest.raises(ValidationError):
            services.assign_judge(
                actor=organizer_account, round_id=round.id,
                submission_id=submission.id, judge_user_id=judge.id,
            )

    def test_nonexistent_judge_raises_not_found(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        submission = SubmissionFactory(team__hackathon=hackathon)
        with pytest.raises(NotFound):
            services.assign_judge(
                actor=organizer_account, round_id=round.id,
                submission_id=submission.id, judge_user_id=uuid.uuid4(),
            )

    def test_duplicate_assignment_is_rejected(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        services.assign_judge(
            actor=organizer_account, round_id=round.id,
            submission_id=submission.id, judge_user_id=judge.id,
        )
        with pytest.raises(services.ConflictError):
            services.assign_judge(
                actor=organizer_account, round_id=round.id,
                submission_id=submission.id, judge_user_id=judge.id,
            )

    def test_cannot_assign_once_the_round_has_opened(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)

        with pytest.raises(ValidationError):
            services.assign_judge(
                actor=organizer_account, round_id=round.id,
                submission_id=submission.id, judge_user_id=judge.id,
            )

    def test_a_tracks_sponsor_cannot_manually_assign_judges(self, hackathon):
        """assign_judge requires the Organizer specifically -- unlike
        rounds/criteria, a track Sponsor does not manage assignment."""
        track = ChallengeTrackFactory(hackathon=hackathon)
        sponsor = AccountFactory()
        _grant_sponsor_for_track(sponsor, track)
        round = JudgingRoundFactory(hackathon=hackathon, track=track)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        opt_in = SubmissionTrackFactory(track=track)

        with pytest.raises(PermissionDenied):
            services.assign_judge(
                actor=sponsor, round_id=round.id,
                submission_id=opt_in.submission_id, judge_user_id=judge.id,
            )


class TestAutoDistribute:
    def test_keeps_assignment_spread_at_most_one(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        judges = [AccountFactory() for _ in range(3)]
        for judge in judges:
            _accept_invitation(round, judge)
        submissions = [SubmissionFactory(team__hackathon=hackathon) for _ in range(10)]

        assignments = services.auto_distribute(
            actor=organizer_account, round_id=round.id,
            judge_user_ids=[judge.id for judge in judges],
        )

        counts = [
            JudgingAssignment.objects.filter(round=round, judge_user=judge).count()
            for judge in judges
        ]
        assert max(counts) - min(counts) <= 1
        assert len(assignments) == len(submissions)

    def test_only_distributes_submissions_opted_into_the_track(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        track = ChallengeTrackFactory(hackathon=hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, track=track)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        opted_in = [SubmissionTrackFactory(track=track).submission_id for _ in range(2)]
        SubmissionFactory(team__hackathon=hackathon)  # not opted in -- must be skipped

        services.auto_distribute(actor=organizer_account, round_id=round.id, judge_user_ids=[judge.id])

        assigned_submission_ids = set(
            JudgingAssignment.objects.filter(round=round).values_list("submission_id", flat=True)
        )
        assert assigned_submission_ids == set(opted_in)

    def test_at_least_one_judge_is_required(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        with pytest.raises(ValidationError):
            services.auto_distribute(actor=organizer_account, round_id=round.id, judge_user_ids=[])

    def test_all_requested_judges_must_exist(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        with pytest.raises(ValidationError):
            services.auto_distribute(
                actor=organizer_account, round_id=round.id,
                judge_user_ids=[judge.id, uuid.uuid4()],
            )

    def test_every_judge_must_have_accepted_an_invitation(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        with pytest.raises(ValidationError):
            services.auto_distribute(actor=organizer_account, round_id=round.id, judge_user_ids=[judge.id])

    def test_cannot_distribute_once_the_round_has_opened(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        judge = AccountFactory()
        _accept_invitation(round, judge)
        with pytest.raises(ValidationError):
            services.auto_distribute(actor=organizer_account, round_id=round.id, judge_user_ids=[judge.id])

    def test_a_tracks_sponsor_cannot_auto_distribute(self, hackathon):
        track = ChallengeTrackFactory(hackathon=hackathon)
        sponsor = AccountFactory()
        _grant_sponsor_for_track(sponsor, track)
        round = JudgingRoundFactory(hackathon=hackathon, track=track)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        with pytest.raises(PermissionDenied):
            services.auto_distribute(actor=sponsor, round_id=round.id, judge_user_ids=[judge.id])


class TestRemoveAssignment:
    def test_removes_an_unscored_assignment(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        assignment = JudgingAssignmentFactory(round=round)

        services.remove_assignment(actor=organizer_account, assignment_id=assignment.id)

        assert not JudgingAssignment.objects.filter(id=assignment.id).exists()

    def test_removal_is_blocked_once_scores_exist_without_confirmation(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, weight=100)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        assignment = JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)
        services.submit_score(
            actor=judge, submission_id=submission.id, criterion_id=criterion.id, score_value=5,
        )
        round.status = "not_started"
        round.save(update_fields=["status"])

        with pytest.raises(services.ConflictError):
            services.remove_assignment(actor=organizer_account, assignment_id=assignment.id)

    def test_confirming_discards_scores_and_removes_the_assignment(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, weight=100)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        assignment = JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)
        services.submit_score(
            actor=judge, submission_id=submission.id, criterion_id=criterion.id, score_value=5,
        )
        round.status = "not_started"
        round.save(update_fields=["status"])

        services.remove_assignment(
            actor=organizer_account, assignment_id=assignment.id, confirm_score_discard=True,
        )

        assert not JudgingAssignment.objects.filter(id=assignment.id).exists()
        assert not Score.objects.filter(submission=submission, judge_user=judge).exists()

    def test_cannot_remove_once_the_round_has_opened(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        assignment = JudgingAssignmentFactory(round=round)
        with pytest.raises(ValidationError):
            services.remove_assignment(actor=organizer_account, assignment_id=assignment.id)

    def test_non_organizer_cannot_remove_an_assignment(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        assignment = JudgingAssignmentFactory(round=round)
        with pytest.raises(PermissionDenied):
            services.remove_assignment(actor=AccountFactory(), assignment_id=assignment.id)

    def test_nonexistent_assignment_raises_not_found(self, organizer_account):
        with pytest.raises(NotFound):
            services.remove_assignment(actor=organizer_account, assignment_id=uuid.uuid4())


class TestReassignJudge:
    def test_reassignment_after_scoring_requires_explicit_discard_confirmation(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        criterion = JudgingCriterionFactory(round=round, weight=100)
        old_judge, new_judge = AccountFactory(), AccountFactory()
        _accept_invitation(round, old_judge)
        _accept_invitation(round, new_judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        assignment = JudgingAssignmentFactory(round=round, submission=submission, judge_user=old_judge)
        round.status = "open"
        round.save(update_fields=["status"])
        services.submit_score(
            actor=old_judge, submission_id=submission.id, criterion_id=criterion.id, score_value=7,
        )
        round.status = "not_started"
        round.save(update_fields=["status"])

        with pytest.raises(services.ConflictError):
            services.reassign_judge(
                actor=organizer_account, assignment_id=assignment.id, new_judge_user_id=new_judge.id,
            )

        updated = services.reassign_judge(
            actor=organizer_account, assignment_id=assignment.id,
            new_judge_user_id=new_judge.id, confirm_score_discard=True,
        )
        assert updated.judge_user_id == new_judge.id
        assert not Score.objects.filter(
            submission=submission, judge_user=old_judge, criterion=criterion,
        ).exists()

    def test_reassigns_to_a_judge_with_no_prior_scores(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        old_judge, new_judge = AccountFactory(), AccountFactory()
        _accept_invitation(round, new_judge)
        assignment = JudgingAssignmentFactory(round=round, judge_user=old_judge)

        updated = services.reassign_judge(
            actor=organizer_account, assignment_id=assignment.id, new_judge_user_id=new_judge.id,
        )

        assert updated.judge_user_id == new_judge.id
        assert updated.reassigned_from_user_id == old_judge.id

    def test_new_judge_must_have_accepted_an_invitation(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        assignment = JudgingAssignmentFactory(round=round)
        new_judge = AccountFactory()

        with pytest.raises(ValidationError):
            services.reassign_judge(
                actor=organizer_account, assignment_id=assignment.id, new_judge_user_id=new_judge.id,
            )

    def test_new_judge_cannot_already_be_assigned_to_the_submission(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        submission = SubmissionFactory(team__hackathon=hackathon)
        new_judge = AccountFactory()
        _accept_invitation(round, new_judge)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=new_judge)
        assignment = JudgingAssignmentFactory(round=round, submission=submission)

        with pytest.raises(services.ConflictError):
            services.reassign_judge(
                actor=organizer_account, assignment_id=assignment.id, new_judge_user_id=new_judge.id,
            )

    def test_nonexistent_new_judge_raises_not_found(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        assignment = JudgingAssignmentFactory(round=round)
        with pytest.raises(NotFound):
            services.reassign_judge(
                actor=organizer_account, assignment_id=assignment.id, new_judge_user_id=uuid.uuid4(),
            )

    def test_cannot_reassign_once_the_round_has_opened(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        assignment = JudgingAssignmentFactory(round=round)
        new_judge = AccountFactory()
        _accept_invitation(round, new_judge)
        with pytest.raises(ValidationError):
            services.reassign_judge(
                actor=organizer_account, assignment_id=assignment.id, new_judge_user_id=new_judge.id,
            )

    def test_non_organizer_cannot_reassign(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        assignment = JudgingAssignmentFactory(round=round)
        with pytest.raises(PermissionDenied):
            services.reassign_judge(
                actor=AccountFactory(), assignment_id=assignment.id, new_judge_user_id=uuid.uuid4(),
            )

    def test_nonexistent_assignment_raises_not_found(self, organizer_account):
        with pytest.raises(NotFound):
            services.reassign_judge(
                actor=organizer_account, assignment_id=uuid.uuid4(), new_judge_user_id=uuid.uuid4(),
            )


class TestListAssignments:
    def test_organizer_sees_every_assignment_in_the_round(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        a1 = JudgingAssignmentFactory(round=round)
        a2 = JudgingAssignmentFactory(round=round)

        assignments = services.list_assignments(actor=organizer_account, round_id=round.id)

        assert {a.id for a in assignments} == {a1.id, a2.id}

    def test_organizer_can_filter_by_judge(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        mine = JudgingAssignmentFactory(round=round, judge_user=judge)
        JudgingAssignmentFactory(round=round)

        assignments = services.list_assignments(
            actor=organizer_account, round_id=round.id, judge_user_id=str(judge.id),
        )

        assert [a.id for a in assignments] == [mine.id]

    def test_a_judge_can_list_only_their_own_assignments(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        judge = AccountFactory()
        mine = JudgingAssignmentFactory(round=round, judge_user=judge)
        JudgingAssignmentFactory(round=round)

        assignments = services.list_assignments(
            actor=judge, round_id=round.id, judge_user_id=str(judge.id),
        )

        assert [a.id for a in assignments] == [mine.id]

    def test_a_judge_cannot_list_someone_elses_assignments(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        other_judge = AccountFactory()
        with pytest.raises(PermissionDenied):
            services.list_assignments(
                actor=AccountFactory(), round_id=round.id, judge_user_id=str(other_judge.id),
            )

    def test_nonexistent_round_raises_not_found(self, organizer_account):
        with pytest.raises(NotFound):
            services.list_assignments(actor=organizer_account, round_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# FR-JUDGE-002: scoring
# ---------------------------------------------------------------------------


class TestSubmitScore:
    def test_out_of_range_score_is_rejected(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, min_score=1, max_score=5, weight=100)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)

        with pytest.raises(ValidationError):
            services.submit_score(
                actor=judge, submission_id=submission.id, criterion_id=criterion.id, score_value=6,
            )

    def test_final_score_cannot_be_edited_by_judge(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, weight=100)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)

        services.submit_score(
            actor=judge, submission_id=submission.id, criterion_id=criterion.id, score_value=7,
        )
        with pytest.raises(services.ConflictError):
            services.submit_score(
                actor=judge, submission_id=submission.id, criterion_id=criterion.id, score_value=8,
            )

    def test_a_draft_score_can_be_revised_by_the_judge(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, weight=100)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)

        services.submit_score(
            actor=judge, submission_id=submission.id, criterion_id=criterion.id,
            score_value=3, status="draft",
        )
        revised = services.submit_score(
            actor=judge, submission_id=submission.id, criterion_id=criterion.id,
            score_value=9, status="draft",
        )

        assert revised.score_value == 9
        assert Score.objects.filter(submission=submission, judge_user=judge).count() == 1

    def test_a_draft_score_does_not_require_a_fully_weighted_rubric(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, weight=40)  # not 100 on its own
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)

        draft = services.submit_score(
            actor=judge, submission_id=submission.id, criterion_id=criterion.id,
            score_value=5, status="draft",
        )
        assert draft.status == "draft"

        with pytest.raises(ValidationError):
            services.submit_score(
                actor=judge, submission_id=submission.id, criterion_id=criterion.id,
                score_value=5, status="final",
            )

    def test_only_the_assigned_judge_can_score_a_submission(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, weight=100)
        submission = SubmissionFactory(team__hackathon=hackathon)

        with pytest.raises(PermissionDenied):
            services.submit_score(
                actor=AccountFactory(), submission_id=submission.id,
                criterion_id=criterion.id, score_value=5,
            )

    def test_scores_cannot_be_saved_before_the_round_opens(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="not_started")
        criterion = JudgingCriterionFactory(round=round, weight=100)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)

        with pytest.raises(ValidationError):
            services.submit_score(
                actor=judge, submission_id=submission.id, criterion_id=criterion.id, score_value=5,
            )

    def test_submission_must_belong_to_the_criterions_round(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, weight=100)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        other_submission = SubmissionFactory()

        with pytest.raises(ValidationError):
            services.submit_score(
                actor=judge, submission_id=other_submission.id,
                criterion_id=criterion.id, score_value=5,
            )

    def test_nonexistent_criterion_raises_not_found(self, hackathon):
        submission = SubmissionFactory(team__hackathon=hackathon)
        with pytest.raises(NotFound):
            services.submit_score(
                actor=AccountFactory(), submission_id=submission.id,
                criterion_id=uuid.uuid4(), score_value=5,
            )

    def test_nonexistent_submission_raises_not_found(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, weight=100)
        with pytest.raises(NotFound):
            services.submit_score(
                actor=AccountFactory(), submission_id=uuid.uuid4(),
                criterion_id=criterion.id, score_value=5,
            )

    def test_a_reopened_final_score_can_be_resubmitted_while_the_round_is_closed(self, hackathon, organizer_account):
        """FR-JUDGE-002/003: reopening a score is the one way a judge can
        still write while the round is closed, and doing so must feed
        back into the materialized results (services.calculate_round_results)."""
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, weight=100)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)
        services.submit_score(
            actor=judge, submission_id=submission.id, criterion_id=criterion.id, score_value=4,
        )
        score = Score.objects.get(submission=submission, judge_user=judge, criterion=criterion)

        services.close_round(actor=organizer_account, round_id=round.id)
        services.reopen_score(actor=organizer_account, score_id=score.id, reason="Judge flagged a mistake.")

        revised = services.submit_score(
            actor=judge, submission_id=submission.id, criterion_id=criterion.id, score_value=9,
        )

        assert revised.status == "final"
        result = round.results.get(submission=submission)
        assert result.aggregate_score == Decimal("9.00")


class TestReopenScore:
    def test_reopening_reverts_status_and_writes_an_audit_entry(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, weight=100)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)
        services.submit_score(
            actor=judge, submission_id=submission.id, criterion_id=criterion.id, score_value=6,
        )
        score = Score.objects.get(submission=submission, judge_user=judge, criterion=criterion)

        reopened = services.reopen_score(
            actor=organizer_account, score_id=score.id, reason="Scored the wrong criterion by mistake.",
        )

        assert reopened.status == "draft"
        assert reopened.reopened_at is not None
        assert AuditLogEntry.objects.filter(
            action="judging.score_reopened", target_type="score", target_id=str(score.id),
        ).exists()

    def test_reason_must_be_at_least_10_characters(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon)
        criterion = JudgingCriterionFactory(round=round, weight=100)
        judge = AccountFactory()
        submission = SubmissionFactory(team__hackathon=hackathon)
        score = Score.objects.create(
            submission=submission, judge_user=judge, criterion=criterion,
            score_value=5, status="final",
        )
        with pytest.raises(ValidationError):
            services.reopen_score(actor=organizer_account, score_id=score.id, reason="too short")

    def test_non_organizer_cannot_reopen_a_score(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon)
        criterion = JudgingCriterionFactory(round=round, weight=100)
        judge = AccountFactory()
        submission = SubmissionFactory(team__hackathon=hackathon)
        score = Score.objects.create(
            submission=submission, judge_user=judge, criterion=criterion,
            score_value=5, status="final",
        )
        with pytest.raises(PermissionDenied):
            services.reopen_score(
                actor=AccountFactory(), score_id=score.id, reason="A perfectly good reason.",
            )

    def test_nonexistent_score_raises_not_found(self, organizer_account):
        with pytest.raises(NotFound):
            services.reopen_score(
                actor=organizer_account, score_id=uuid.uuid4(), reason="A perfectly good reason.",
            )


class TestListSubmissionScores:
    def test_organizer_sees_every_judges_scores_ordered(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, weight=100)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)
        services.submit_score(
            actor=judge, submission_id=submission.id, criterion_id=criterion.id, score_value=8,
        )

        scores = services.list_submission_scores(actor=organizer_account, submission_id=submission.id)

        assert [s.score_value for s in scores] == [8]

    def test_non_organizer_cannot_view_scores(self, hackathon):
        submission = SubmissionFactory(team__hackathon=hackathon)
        with pytest.raises(PermissionDenied):
            services.list_submission_scores(actor=AccountFactory(), submission_id=submission.id)

    def test_nonexistent_submission_raises_not_found(self, organizer_account):
        with pytest.raises(NotFound):
            services.list_submission_scores(actor=organizer_account, submission_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# FR-JUDGE-003: result calculation
# ---------------------------------------------------------------------------


class TestCalculateRoundResults:
    def test_weighted_mean_is_calculated_and_ranked(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        c1 = JudgingCriterionFactory(round=round, min_score=0, max_score=10, weight=60)
        c2 = JudgingCriterionFactory(round=round, min_score=0, max_score=10, weight=40)
        judges = [AccountFactory(), AccountFactory()]
        submissions = [SubmissionFactory(team__hackathon=hackathon) for _ in range(2)]

        for judge in judges:
            _accept_invitation(round, judge)
        for submission, values in zip(submissions, [(10, 10), (5, 5)]):
            for judge in judges:
                JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)
                services.submit_score(
                    actor=judge, submission_id=submission.id, criterion_id=c1.id, score_value=values[0],
                )
                services.submit_score(
                    actor=judge, submission_id=submission.id, criterion_id=c2.id, score_value=values[1],
                )
        round.status = "closed"
        round.save(update_fields=["status"])

        results = services.calculate_round_results(round_id=round.id)

        assert [result.aggregate_score for result in results] == [Decimal("10.00"), Decimal("5.00")]
        assert [result.rank for result in results] == [1, 2]

    def test_zero_judge_submission_is_excluded(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="closed")
        JudgingCriterionFactory(round=round, weight=100)
        submission = SubmissionFactory(team__hackathon=hackathon)

        results = services.calculate_round_results(round_id=round.id)

        assert results == []
        assert not round.results.filter(submission=submission).exists()

    def test_a_judge_who_only_scored_part_of_the_rubric_is_excluded(self, hackathon, organizer_account):
        """A partial rubric never silently counts as a zero -- it's simply
        not counted (services.calculate_round_results)."""
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        c1 = JudgingCriterionFactory(round=round, weight=60)
        c2 = JudgingCriterionFactory(round=round, weight=40)
        complete_judge, partial_judge = AccountFactory(), AccountFactory()
        submission = SubmissionFactory(team__hackathon=hackathon)
        for judge in (complete_judge, partial_judge):
            _accept_invitation(round, judge)
            JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)

        services.submit_score(
            actor=complete_judge, submission_id=submission.id, criterion_id=c1.id, score_value=8,
        )
        services.submit_score(
            actor=complete_judge, submission_id=submission.id, criterion_id=c2.id, score_value=8,
        )
        # partial_judge only scores one of the two criteria.
        services.submit_score(
            actor=partial_judge, submission_id=submission.id, criterion_id=c1.id, score_value=2,
        )
        round.status = "closed"
        round.save(update_fields=["status"])

        results = services.calculate_round_results(round_id=round.id)

        assert len(results) == 1
        assert results[0].aggregate_score == Decimal("8.00")

    def test_recalculation_replaces_prior_results(self, hackathon, organizer_account):
        _grant_organizer(organizer_account, hackathon)
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        criterion = JudgingCriterionFactory(round=round, weight=100)
        judge = AccountFactory()
        _accept_invitation(round, judge)
        submission = SubmissionFactory(team__hackathon=hackathon)
        JudgingAssignmentFactory(round=round, submission=submission, judge_user=judge)
        services.submit_score(
            actor=judge, submission_id=submission.id, criterion_id=criterion.id, score_value=5,
        )
        round.status = "closed"
        round.save(update_fields=["status"])
        services.calculate_round_results(round_id=round.id)

        results = services.calculate_round_results(round_id=round.id)

        assert round.results.count() == 1
        assert results[0].aggregate_score == Decimal("5.00")

    def test_cannot_calculate_results_before_the_round_closes(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="open")
        JudgingCriterionFactory(round=round, weight=100)
        with pytest.raises(ValidationError):
            services.calculate_round_results(round_id=round.id)

    def test_a_closed_round_with_no_criteria_produces_no_results(self, hackathon):
        round = JudgingRoundFactory(hackathon=hackathon, status="closed")
        assert services.calculate_round_results(round_id=round.id) == []