"""
Unit tests against hackathons/services.py directly (Design Spec Sec 3.1),
per the 80% coverage target in NFR-MAINT-001.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import RoleAssignment
from apps.core.models import AuditLogEntry
from apps.hackathons import services
from apps.hackathons.models import Hackathon
from apps.organizations.tests.factories import OrganizationFactory, VerifiedOrganizationFactory

from .factories import (
    ArchivedHackathonFactory,
    ChallengeTrackFactory,
    HackathonFactory,
    PublishedHackathonFactory,
)


def _timeline(**overrides):
    now = timezone.now()
    base = dict(
        registration_opens_at=now,
        registration_closes_at=now + timedelta(days=7),
        submission_opens_at=now + timedelta(days=7),
        submission_closes_at=now + timedelta(days=14),
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# FR-HACK-001: create a hackathon
# ---------------------------------------------------------------------------


class TestCreateHackathon:
    def test_creates_draft_hackathon(self, organizer_account, verified_org, organizer_role):
        hackathon = services.create_hackathon(
            actor=organizer_account, host_org_id=verified_org.id, title="AAU Hack", **_timeline(),
        )
        assert hackathon.status == "draft"
        assert hackathon.host_org_id == verified_org.id
        assert hackathon.slug

    def test_non_organizer_is_forbidden(self, organizer_account, verified_org):
        with pytest.raises(PermissionDenied):
            services.create_hackathon(
                actor=organizer_account, host_org_id=verified_org.id, title="AAU Hack", **_timeline(),
            )

    def test_unverified_org_is_forbidden(self, organizer_account):
        org = OrganizationFactory(created_by=organizer_account, verification_status="unverified")
        RoleAssignment.objects.create(
            user=organizer_account, role="organizer", scope_type="organization", scope_id=org.id,
        )
        with pytest.raises(PermissionDenied):
            services.create_hackathon(actor=organizer_account, host_org_id=org.id, title="AAU Hack", **_timeline())

    def test_registration_close_before_open_is_rejected(self, organizer_account, verified_org, organizer_role):
        now = timezone.now()
        with pytest.raises(ValidationError):
            services.create_hackathon(
                actor=organizer_account, host_org_id=verified_org.id, title="AAU Hack",
                **_timeline(registration_opens_at=now, registration_closes_at=now - timedelta(days=1)),
            )

    def test_submission_close_before_registration_close_is_rejected(self, organizer_account, verified_org, organizer_role):
        now = timezone.now()
        with pytest.raises(ValidationError):
            services.create_hackathon(
                actor=organizer_account, host_org_id=verified_org.id, title="AAU Hack",
                **_timeline(
                    registration_closes_at=now + timedelta(days=10),
                    submission_opens_at=now + timedelta(days=1),
                    submission_closes_at=now + timedelta(days=2),
                ),
            )

    def test_registration_deadline_in_the_past_is_rejected(self, organizer_account, verified_org, organizer_role):
        now = timezone.now()
        with pytest.raises(ValidationError):
            services.create_hackathon(
                actor=organizer_account, host_org_id=verified_org.id, title="AAU Hack",
                **_timeline(
                    registration_opens_at=now - timedelta(days=10),
                    registration_closes_at=now - timedelta(days=1),
                ),
            )

    def test_writes_audit_log_entry(self, organizer_account, verified_org, organizer_role):
        hackathon = services.create_hackathon(
            actor=organizer_account, host_org_id=verified_org.id, title="AAU Hack", **_timeline(),
        )
        assert AuditLogEntry.objects.filter(action="hackathon.created", target_id=str(hackathon.id)).exists()

    def test_duplicate_slug_is_rejected(self, organizer_account, verified_org, organizer_role):
        services.create_hackathon(
            actor=organizer_account, host_org_id=verified_org.id, title="AAU Hack", slug="aau-hack", **_timeline(),
        )
        with pytest.raises(ValidationError):
            services.create_hackathon(
                actor=organizer_account, host_org_id=verified_org.id, title="AAU Hack 2", slug="aau-hack", **_timeline(),
            )

    def test_nonexistent_org_raises_not_found(self, organizer_account):
        with pytest.raises(NotFound):
            services.create_hackathon(actor=organizer_account, host_org_id=uuid.uuid4(), title="X", **_timeline())


# ---------------------------------------------------------------------------
# FR-DISC-003: get a hackathon
# ---------------------------------------------------------------------------


class TestGetHackathon:
    def test_returns_published_hackathon_to_anonymous(self, published_hackathon):
        result = services.get_hackathon(hackathon_id=published_hackathon.id, requester=None)
        assert result.id == published_hackathon.id

    def test_draft_hidden_from_anonymous(self, hackathon):
        with pytest.raises(NotFound):
            services.get_hackathon(hackathon_id=hackathon.id, requester=None)

    def test_draft_visible_to_owning_organizer(self, hackathon, organizer_account, organizer_role):
        result = services.get_hackathon(hackathon_id=hackathon.id, requester=organizer_account)
        assert result.id == hackathon.id

    def test_draft_hidden_from_unrelated_authenticated_user(self, hackathon, other_account):
        with pytest.raises(NotFound):
            services.get_hackathon(hackathon_id=hackathon.id, requester=other_account)


# ---------------------------------------------------------------------------
# FR-DISC-001/002: list hackathons
# ---------------------------------------------------------------------------


class TestListHackathons:
    def test_only_returns_published_and_archived(self, verified_org, organizer_account):
        HackathonFactory(host_org=verified_org, created_by=organizer_account, status="draft")
        published = PublishedHackathonFactory(host_org=verified_org, created_by=organizer_account)
        archived = ArchivedHackathonFactory(host_org=verified_org, created_by=organizer_account)

        results, total = services.list_hackathons()

        ids = {h.id for h in results}
        assert published.id in ids
        assert archived.id in ids
        assert total == 2

    def test_draft_status_filter_returns_empty_not_an_error(self, published_hackathon):
        results, total = services.list_hackathons(status="draft")
        assert results == []
        assert total == 0

    def test_keyword_filters_by_title(self, verified_org, organizer_account):
        match = PublishedHackathonFactory(host_org=verified_org, created_by=organizer_account, title="EthioHacks 2026")
        PublishedHackathonFactory(host_org=verified_org, created_by=organizer_account, title="Something Else")

        results, total = services.list_hackathons(keyword="ethiohacks")

        assert total == 1
        assert results[0].id == match.id

    def test_tag_filter(self, verified_org, organizer_account):
        match = PublishedHackathonFactory(host_org=verified_org, created_by=organizer_account, tags=["fintech"])
        PublishedHackathonFactory(host_org=verified_org, created_by=organizer_account, tags=["health"])

        results, total = services.list_hackathons(tag="fintech")

        assert total == 1
        assert results[0].id == match.id

    def test_pagination_limit_and_offset(self, verified_org, organizer_account):
        for _ in range(5):
            PublishedHackathonFactory(host_org=verified_org, created_by=organizer_account)

        results, total = services.list_hackathons(limit=2, offset=2)

        assert total == 5
        assert len(results) == 2


# ---------------------------------------------------------------------------
# FR-HACK-002/003/005: update + status transitions
# ---------------------------------------------------------------------------


class TestUpdateHackathon:
    def test_organizer_can_update_title(self, hackathon, organizer_account, organizer_role):
        updated = services.update_hackathon(
            actor=organizer_account, hackathon_id=hackathon.id, data={"title": "New Title"},
        )
        assert updated.title == "New Title"

    def test_non_organizer_is_forbidden(self, hackathon, other_account):
        with pytest.raises(PermissionDenied):
            services.update_hackathon(actor=other_account, hackathon_id=hackathon.id, data={"title": "X"})

    def test_publish_with_missing_fields_is_rejected(self, organizer_account, verified_org, organizer_role):
        incomplete = HackathonFactory(host_org=verified_org, created_by=organizer_account, eligibility_rules=None)
        with pytest.raises(ValidationError):
            services.update_hackathon(actor=organizer_account, hackathon_id=incomplete.id, data={"status": "published"})

    def test_publish_succeeds_when_complete(self, hackathon, organizer_account, organizer_role):
        updated = services.update_hackathon(actor=organizer_account, hackathon_id=hackathon.id, data={"status": "published"})
        assert updated.status == "published"

    def test_unpublish_requires_published_status(self, hackathon, organizer_account, organizer_role):
        with pytest.raises(ValidationError):
            services.update_hackathon(actor=organizer_account, hackathon_id=hackathon.id, data={"status": "draft"})

    def test_archive_before_end_date_is_rejected(self, published_hackathon, organizer_account, organizer_role):
        with pytest.raises(ValidationError):
            services.update_hackathon(actor=organizer_account, hackathon_id=published_hackathon.id, data={"status": "archived"})

    def test_editing_archived_hackathon_is_rejected(self, verified_org, organizer_account, organizer_role):
        archived = ArchivedHackathonFactory(host_org=verified_org, created_by=organizer_account)
        with pytest.raises(ValidationError):
            services.update_hackathon(actor=organizer_account, hackathon_id=archived.id, data={"title": "New"})


# ---------------------------------------------------------------------------
# DELETE /hackathons/{id}
# ---------------------------------------------------------------------------


class TestDeleteHackathon:
    def test_deletes_draft_hackathon(self, hackathon, organizer_account, organizer_role):
        services.delete_hackathon(actor=organizer_account, hackathon_id=hackathon.id)
        assert not Hackathon.objects.filter(id=hackathon.id).exists()

    def test_cannot_delete_published_hackathon(self, published_hackathon, organizer_account, organizer_role):
        with pytest.raises(ValidationError):
            services.delete_hackathon(actor=organizer_account, hackathon_id=published_hackathon.id)

    def test_non_organizer_is_forbidden(self, hackathon, other_account):
        with pytest.raises(PermissionDenied):
            services.delete_hackathon(actor=other_account, hackathon_id=hackathon.id)


# ---------------------------------------------------------------------------
# FR-TRACK-001
# ---------------------------------------------------------------------------


class TestChallengeTracks:
    def test_organizer_can_create_track(self, hackathon, organizer_account, organizer_role):
        sponsor_org = VerifiedOrganizationFactory()
        track = services.create_challenge_track(
            actor=organizer_account, hackathon_id=hackathon.id, sponsor_org_id=sponsor_org.id, name="AI Track",
        )
        assert track.hackathon_id == hackathon.id

    def test_non_organizer_is_forbidden(self, hackathon, other_account):
        sponsor_org = VerifiedOrganizationFactory()
        with pytest.raises(PermissionDenied):
            services.create_challenge_track(
                actor=other_account, hackathon_id=hackathon.id, sponsor_org_id=sponsor_org.id, name="AI Track",
            )

    def test_duplicate_track_name_is_rejected(self, hackathon, organizer_account, organizer_role):
        sponsor_org = VerifiedOrganizationFactory()
        ChallengeTrackFactory(hackathon=hackathon, name="AI Track")
        with pytest.raises(ValidationError):
            services.create_challenge_track(
                actor=organizer_account, hackathon_id=hackathon.id, sponsor_org_id=sponsor_org.id, name="AI Track",
            )

    def test_list_returns_tracks_for_hackathon(self, hackathon):
        track = ChallengeTrackFactory(hackathon=hackathon)
        results = list(services.list_challenge_tracks(hackathon_id=hackathon.id))
        assert results == [track]

# ---------------------------------------------------------------------------
# FR-ELIG-001: screen a submission's eligibility
# ---------------------------------------------------------------------------


class TestScreenSubmission:
    """screen_submission's own precondition/permission behavior wasn't
    covered by any existing test before this notification wiring -- these
    focus on the one thing that changed (the FR-NOTIFY-001 side effect),
    plus the minimum surrounding coverage needed to reach it."""

    @pytest.fixture
    def locked_submission(self, organizer_account):
        from apps.submissions.tests.factories import SubmissionFactory
        from apps.teams.tests.factories import AcceptedTeamMemberFactory, TeamFactory

        hackathon = ArchivedHackathonFactory(created_by=organizer_account)
        team = TeamFactory(hackathon=hackathon)
        AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=team.leader_user)
        return SubmissionFactory(team=team, hackathon=hackathon)

    def test_disqualifying_notifies_the_team(self, locked_submission, organizer_account):
        from apps.notifications.models import NotificationDelivery

        RoleAssignment.objects.create(
            user=organizer_account, role="organizer", scope_type="organization",
            scope_id=locked_submission.hackathon.host_org_id,
        )

        services.screen_submission(
            actor=organizer_account, submission_id=locked_submission.id,
            eligibility_status="disqualified", reason="Violated the no-AI-generated-code rule.",
        )

        assert NotificationDelivery.objects.filter(
            user=locked_submission.team.leader_user, channel="in_portal",
        ).exists()

    def test_reinstating_to_eligible_also_notifies(self, locked_submission, organizer_account):
        from apps.notifications.models import NotificationDelivery

        RoleAssignment.objects.create(
            user=organizer_account, role="organizer", scope_type="organization",
            scope_id=locked_submission.hackathon.host_org_id,
        )
        locked_submission.eligibility_status = "disqualified"
        locked_submission.save(update_fields=["eligibility_status"])

        services.screen_submission(
            actor=organizer_account, submission_id=locked_submission.id, eligibility_status="eligible",
        )

        assert NotificationDelivery.objects.filter(
            user=locked_submission.team.leader_user, channel="in_portal",
        ).exists()

    def test_unlocked_submission_is_rejected_before_any_notification(self, organizer_account):
        from apps.notifications.models import NotificationDelivery
        from apps.submissions.tests.factories import SubmissionFactory
        from apps.teams.tests.factories import TeamFactory

        hackathon = PublishedHackathonFactory(created_by=organizer_account)  # submission_closes_at is in the future
        team = TeamFactory(hackathon=hackathon)
        submission = SubmissionFactory(team=team, hackathon=hackathon)
        RoleAssignment.objects.create(
            user=organizer_account, role="organizer", scope_type="organization", scope_id=hackathon.host_org_id,
        )

        with pytest.raises(ValidationError):
            services.screen_submission(
                actor=organizer_account, submission_id=submission.id, eligibility_status="disqualified",
                reason="Too early to screen this one.",
            )

        assert not NotificationDelivery.objects.exists()


# ---------------------------------------------------------------------------
# FR-ELIG-002: list submissions for screening (incl. trackId filter)
# ---------------------------------------------------------------------------


class TestListSubmissionsForScreening:
    @pytest.fixture
    def locked_hackathon(self, verified_org, organizer_account, organizer_role):
        return ArchivedHackathonFactory(host_org=verified_org, created_by=organizer_account)

    def _submission_in(self, hackathon):
        from apps.submissions.tests.factories import SubmissionFactory
        from apps.teams.tests.factories import TeamFactory

        team = TeamFactory(hackathon=hackathon)
        return SubmissionFactory(team=team, hackathon=hackathon)

    def test_non_organizer_is_forbidden(self, locked_hackathon):
        from apps.accounts.tests.factories import AccountFactory

        stranger = AccountFactory()
        with pytest.raises(PermissionDenied):
            services.list_submissions_for_screening(actor=stranger, hackathon_id=locked_hackathon.id)

    def test_before_submission_deadline_returns_empty(self, published_hackathon, organizer_account, organizer_role):
        self._submission_in(published_hackathon)

        results, total = services.list_submissions_for_screening(
            actor=organizer_account, hackathon_id=published_hackathon.id,
        )

        assert results == []
        assert total == 0

    def test_lists_locked_submissions(self, locked_hackathon, organizer_account):
        submission = self._submission_in(locked_hackathon)

        results, total = services.list_submissions_for_screening(
            actor=organizer_account, hackathon_id=locked_hackathon.id,
        )

        assert results == [submission]
        assert total == 1

    def test_filters_by_eligibility_status(self, locked_hackathon, organizer_account):
        eligible = self._submission_in(locked_hackathon)
        disqualified = self._submission_in(locked_hackathon)
        disqualified.eligibility_status = "disqualified"
        disqualified.save(update_fields=["eligibility_status"])

        results, total = services.list_submissions_for_screening(
            actor=organizer_account, hackathon_id=locked_hackathon.id, eligibility_status="disqualified",
        )

        assert results == [disqualified]
        assert total == 1

    def test_invalid_eligibility_status_is_rejected(self, locked_hackathon, organizer_account):
        with pytest.raises(ValidationError):
            services.list_submissions_for_screening(
                actor=organizer_account, hackathon_id=locked_hackathon.id, eligibility_status="not-a-real-status",
            )

    def test_filters_by_track_id(self, locked_hackathon, organizer_account):
        from apps.submissions.tests.factories import SubmissionTrackFactory

        track = ChallengeTrackFactory(hackathon=locked_hackathon)
        other_track = ChallengeTrackFactory(hackathon=locked_hackathon)

        in_track = self._submission_in(locked_hackathon)
        SubmissionTrackFactory(submission=in_track, track=track)

        not_in_track = self._submission_in(locked_hackathon)
        SubmissionTrackFactory(submission=not_in_track, track=other_track)

        results, total = services.list_submissions_for_screening(
            actor=organizer_account, hackathon_id=locked_hackathon.id, track_id=track.id,
        )

        assert results == [in_track]
        assert total == 1

    def test_unknown_track_id_raises_not_found(self, locked_hackathon, organizer_account):
        with pytest.raises(NotFound):
            services.list_submissions_for_screening(
                actor=organizer_account, hackathon_id=locked_hackathon.id, track_id=uuid.uuid4(),
            )

    def test_track_from_a_different_hackathon_is_rejected(self, locked_hackathon, organizer_account):
        other_hackathon = ArchivedHackathonFactory()
        foreign_track = ChallengeTrackFactory(hackathon=other_hackathon)

        with pytest.raises(ValidationError):
            services.list_submissions_for_screening(
                actor=organizer_account, hackathon_id=locked_hackathon.id, track_id=foreign_track.id,
            )