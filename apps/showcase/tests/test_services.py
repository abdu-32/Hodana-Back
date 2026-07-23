"""
Unit tests against showcase/services.py directly (Design Spec Sec 3.1),
per the 80% coverage target in NFR-MAINT-001. Prefer these over
HTTP-level tests for business-rule coverage; apps/showcase/tests/test_api.py
only needs to confirm routing/serialization.
"""

from decimal import Decimal

import pytest
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import RoleAssignment
from apps.accounts.tests.factories import AccountFactory
from apps.core.models import AuditLogEntry
from apps.hackathons.tests.factories import ChallengeTrackFactory
from apps.judging.tests.factories import JudgingRoundFactory, RoundResultFactory
from apps.submissions.tests.factories import SubmissionFactory
from apps.teams.tests.factories import AcceptedTeamMemberFactory

from .. import services
from ..models import ShowcaseOverride
from .factories import ShowcaseOverrideFactory


def _grant_organizer(user, hackathon):
    return RoleAssignment.objects.create(
        user=user, role="organizer", scope_type="organization",
        scope_id=hackathon.host_org_id,
    )


def _closed_overall_round(hackathon):
    return JudgingRoundFactory(hackathon=hackathon, track=None, status="closed")


# ---------------------------------------------------------------------------
# FR-SHOWCASE-001: publish / unpublish
# ---------------------------------------------------------------------------


class TestPublishShowcase:
    def test_organizer_publishes_once_all_rounds_are_closed(self, hackathon, organizer_account, organizer_role):
        _closed_overall_round(hackathon)

        result = services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

        hackathon.refresh_from_db()
        assert result.id == hackathon.id
        assert hackathon.showcase_published_at is not None
        assert AuditLogEntry.objects.filter(
            action="showcase.published", target_id=str(hackathon.id),
        ).exists()

    def test_non_organizer_cannot_publish(self, hackathon):
        _closed_overall_round(hackathon)
        stranger = AccountFactory()

        with pytest.raises(PermissionDenied):
            services.publish_showcase(actor=stranger, hackathon_id=hackathon.id)

    def test_cannot_publish_without_any_judging_rounds(self, hackathon, organizer_account, organizer_role):
        with pytest.raises(ValidationError):
            services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

    def test_cannot_publish_while_a_round_is_still_open(self, hackathon, organizer_account, organizer_role):
        JudgingRoundFactory(hackathon=hackathon, track=None, status="open")

        with pytest.raises(ValidationError):
            services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

    def test_publish_is_idempotent(self, hackathon, organizer_account, organizer_role):
        _closed_overall_round(hackathon)
        services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)
        hackathon.refresh_from_db()
        first_timestamp = hackathon.showcase_published_at

        services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

        hackathon.refresh_from_db()
        assert hackathon.showcase_published_at == first_timestamp

    def test_draft_hackathon_cannot_be_showcased(self, verified_org, organizer_account, organizer_role):
        from apps.hackathons.tests.factories import HackathonFactory
        draft_hackathon = HackathonFactory(host_org=verified_org, created_by=organizer_account, status="draft")
        _closed_overall_round(draft_hackathon)

        with pytest.raises(ValidationError):
            services.publish_showcase(actor=organizer_account, hackathon_id=draft_hackathon.id)


class TestUnpublishShowcase:
    def test_organizer_unpublishes(self, hackathon, organizer_account, organizer_role):
        _closed_overall_round(hackathon)
        services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

        services.unpublish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

        hackathon.refresh_from_db()
        assert hackathon.showcase_published_at is None
        assert AuditLogEntry.objects.filter(
            action="showcase.unpublished", target_id=str(hackathon.id),
        ).exists()

    def test_cannot_unpublish_when_not_published(self, hackathon, organizer_account, organizer_role):
        with pytest.raises(ValidationError):
            services.unpublish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

    def test_non_organizer_cannot_unpublish(self, hackathon, organizer_account, organizer_role):
        _closed_overall_round(hackathon)
        services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)
        stranger = AccountFactory()

        with pytest.raises(PermissionDenied):
            services.unpublish_showcase(actor=stranger, hackathon_id=hackathon.id)


# ---------------------------------------------------------------------------
# FR-SHOWCASE-001: visibility overrides
# ---------------------------------------------------------------------------


class TestSubmissionVisibility:
    def test_organizer_hides_an_eligible_submission_with_a_reason(self, hackathon, organizer_account, organizer_role):
        submission = SubmissionFactory(team__hackathon=hackathon)

        override = services.set_submission_visibility(
            actor=organizer_account, submission_id=submission.id,
            is_visible=False, reason="Plagiarism concerns raised post-judging.",
        )

        assert override.is_visible is False
        assert override.submission_id == submission.id
        assert AuditLogEntry.objects.filter(action="showcase.visibility_overridden").exists()

    def test_reason_must_be_at_least_ten_characters(self, hackathon, organizer_account, organizer_role):
        submission = SubmissionFactory(team__hackathon=hackathon)

        with pytest.raises(ValidationError):
            services.set_submission_visibility(
                actor=organizer_account, submission_id=submission.id,
                is_visible=False, reason="too short",
            )

    def test_non_organizer_cannot_set_visibility(self, hackathon):
        submission = SubmissionFactory(team__hackathon=hackathon)
        stranger = AccountFactory()

        with pytest.raises(PermissionDenied):
            services.set_submission_visibility(
                actor=stranger, submission_id=submission.id,
                is_visible=False, reason="Not my hackathon.",
            )

    def test_setting_visibility_twice_updates_the_same_override(self, hackathon, organizer_account, organizer_role):
        submission = SubmissionFactory(team__hackathon=hackathon)
        services.set_submission_visibility(
            actor=organizer_account, submission_id=submission.id,
            is_visible=False, reason="Initial hide for review.",
        )

        services.set_submission_visibility(
            actor=organizer_account, submission_id=submission.id,
            is_visible=True, reason="Cleared after manual review.",
        )

        assert ShowcaseOverride.objects.filter(submission=submission).count() == 1
        override = ShowcaseOverride.objects.get(submission=submission)
        assert override.is_visible is True

    def test_clear_override_reverts_to_default(self, hackathon, organizer_account, organizer_role):
        submission = SubmissionFactory(team__hackathon=hackathon)
        ShowcaseOverrideFactory(hackathon=hackathon, submission=submission, created_by=organizer_account)

        services.clear_submission_visibility_override(actor=organizer_account, submission_id=submission.id)

        assert not ShowcaseOverride.objects.filter(submission=submission).exists()

    def test_clear_override_404s_when_none_exists(self, hackathon, organizer_account, organizer_role):
        submission = SubmissionFactory(team__hackathon=hackathon)

        with pytest.raises(NotFound):
            services.clear_submission_visibility_override(actor=organizer_account, submission_id=submission.id)


# ---------------------------------------------------------------------------
# FR-SHOWCASE-001: single hackathon's showcase page
# ---------------------------------------------------------------------------


class TestGetHackathonShowcase:
    def test_404s_while_unpublished(self, hackathon):
        with pytest.raises(NotFound):
            services.get_hackathon_showcase(hackathon_id=hackathon.id)

    def test_returns_overall_results_ranked(self, hackathon, organizer_account, organizer_role):
        round = _closed_overall_round(hackathon)
        submission = SubmissionFactory(team__hackathon=hackathon)
        AcceptedTeamMemberFactory(team=submission.team, user=submission.team.leader_user)
        RoundResultFactory(round=round, submission=submission, rank=1, aggregate_score=Decimal("8.50"))
        services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

        showcase = services.get_hackathon_showcase(hackathon_id=hackathon.id)

        assert showcase["hackathon"].id == hackathon.id
        assert len(showcase["overall_results"]) == 1
        row = showcase["overall_results"][0]
        assert row["submission"].id == submission.id
        assert row["rank"] == 1
        assert row["aggregate_score"] == Decimal("8.50")
        assert len(row["team_members"]) == 1

    def test_disqualified_submission_hidden_by_default(self, hackathon, organizer_account, organizer_role):
        round = _closed_overall_round(hackathon)
        submission = SubmissionFactory(
            team__hackathon=hackathon, eligibility_status="disqualified",
        )
        RoundResultFactory(round=round, submission=submission, rank=1)
        services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

        showcase = services.get_hackathon_showcase(hackathon_id=hackathon.id)

        assert showcase["overall_results"] == []

    def test_override_can_show_a_disqualified_submission(self, hackathon, organizer_account, organizer_role):
        round = _closed_overall_round(hackathon)
        submission = SubmissionFactory(
            team__hackathon=hackathon, eligibility_status="disqualified",
        )
        RoundResultFactory(round=round, submission=submission, rank=1)
        ShowcaseOverrideFactory(
            hackathon=hackathon, submission=submission, is_visible=True, created_by=organizer_account,
        )
        services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

        showcase = services.get_hackathon_showcase(hackathon_id=hackathon.id)

        assert [row["submission"].id for row in showcase["overall_results"]] == [submission.id]

    def test_override_can_hide_an_eligible_submission(self, hackathon, organizer_account, organizer_role):
        round = _closed_overall_round(hackathon)
        submission = SubmissionFactory(team__hackathon=hackathon)
        RoundResultFactory(round=round, submission=submission, rank=1)
        ShowcaseOverrideFactory(
            hackathon=hackathon, submission=submission, is_visible=False, created_by=organizer_account,
        )
        services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

        showcase = services.get_hackathon_showcase(hackathon_id=hackathon.id)

        assert showcase["overall_results"] == []

    def test_track_results_are_grouped_separately_from_overall(self, hackathon, organizer_account, organizer_role):
        overall_round = _closed_overall_round(hackathon)
        track = ChallengeTrackFactory(hackathon=hackathon, sponsor_org=hackathon.host_org)
        track_round = JudgingRoundFactory(hackathon=hackathon, track=track, status="closed")

        overall_submission = SubmissionFactory(team__hackathon=hackathon)
        RoundResultFactory(round=overall_round, submission=overall_submission, rank=1)
        track_submission = SubmissionFactory(team__hackathon=hackathon)
        RoundResultFactory(round=track_round, submission=track_submission, rank=1)
        services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

        showcase = services.get_hackathon_showcase(hackathon_id=hackathon.id)

        assert [row["submission"].id for row in showcase["overall_results"]] == [overall_submission.id]
        assert len(showcase["track_results"]) == 1
        assert showcase["track_results"][0]["track"].id == track.id
        assert [row["submission"].id for row in showcase["track_results"][0]["results"]] == [track_submission.id]


# ---------------------------------------------------------------------------
# FR-SHOWCASE-002: cross-hackathon gallery
# ---------------------------------------------------------------------------


class TestListGallery:
    def _publish(self, hackathon, organizer_account, organizer_role_fixture):
        _closed_overall_round(hackathon)
        services.publish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

    def test_only_published_hackathons_appear(self, hackathon, organizer_account, organizer_role):
        published_submission = SubmissionFactory(team__hackathon=hackathon)
        self._publish(hackathon, organizer_account, organizer_role)

        from apps.hackathons.tests.factories import PublishedHackathonFactory
        other_hackathon = PublishedHackathonFactory()
        SubmissionFactory(team__hackathon=other_hackathon)

        rows, total = services.list_gallery()

        assert total == 1
        assert rows[0]["submission"].id == published_submission.id

    def test_filters_by_hackathon_id(self, hackathon, organizer_account, organizer_role):
        submission = SubmissionFactory(team__hackathon=hackathon)
        self._publish(hackathon, organizer_account, organizer_role)

        rows, total = services.list_gallery(hackathon_id=hackathon.id)

        assert total == 1
        assert rows[0]["submission"].id == submission.id

    def test_filters_by_institution_org_id(self, hackathon, organizer_account, organizer_role):
        SubmissionFactory(team__hackathon=hackathon)
        self._publish(hackathon, organizer_account, organizer_role)

        from apps.organizations.tests.factories import VerifiedOrganizationFactory
        rows, total = services.list_gallery(institution_org_id=VerifiedOrganizationFactory().id)

        assert total == 0

    def test_filters_by_tag(self, hackathon, organizer_account, organizer_role):
        matching = SubmissionFactory(
            team__hackathon=hackathon, technologies=["django", "postgres"],
        )
        SubmissionFactory(team__hackathon=hackathon, technologies=["react"])
        self._publish(hackathon, organizer_account, organizer_role)

        rows, total = services.list_gallery(tag="django")

        assert total == 1
        assert rows[0]["submission"].id == matching.id

    def test_excludes_disqualified_submissions_by_default(self, hackathon, organizer_account, organizer_role):
        SubmissionFactory(team__hackathon=hackathon, eligibility_status="disqualified")
        self._publish(hackathon, organizer_account, organizer_role)

        rows, total = services.list_gallery()

        assert total == 0

    def test_hidden_override_excludes_an_otherwise_eligible_submission(self, hackathon, organizer_account, organizer_role):
        submission = SubmissionFactory(team__hackathon=hackathon)
        ShowcaseOverrideFactory(
            hackathon=hackathon, submission=submission, is_visible=False, created_by=organizer_account,
        )
        self._publish(hackathon, organizer_account, organizer_role)

        rows, total = services.list_gallery()

        assert total == 0

    def test_unpublishing_removes_projects_from_the_gallery(self, hackathon, organizer_account, organizer_role):
        SubmissionFactory(team__hackathon=hackathon)
        self._publish(hackathon, organizer_account, organizer_role)
        services.unpublish_showcase(actor=organizer_account, hackathon_id=hackathon.id)

        rows, total = services.list_gallery()

        assert total == 0

    def test_pagination(self, hackathon, organizer_account, organizer_role):
        for _ in range(3):
            SubmissionFactory(team__hackathon=hackathon)
        self._publish(hackathon, organizer_account, organizer_role)

        rows, total = services.list_gallery(limit=2, offset=0)
        assert total == 3
        assert len(rows) == 2

        rows, total = services.list_gallery(limit=2, offset=2)
        assert total == 3
        assert len(rows) == 1