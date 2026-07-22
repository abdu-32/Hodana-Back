"""
Unit tests against submissions/services.py directly (Design Spec Sec 3.1),
per the 80% coverage target in NFR-MAINT-001. Prefer these over
HTTP-level tests for business-rule coverage.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.tests.factories import AccountFactory, RoleAssignmentFactory
from apps.core.models import AuditLogEntry
from apps.hackathons.tests.factories import (
    ChallengeTrackFactory,
    PublishedHackathonFactory,
)
from apps.registrations.tests.factories import RegistrationFactory
from apps.submissions import services
from apps.submissions.models import Submission, SubmissionVersion, SubmissionTrack
from apps.teams.tests.factories import AcceptedTeamMemberFactory, TeamFactory

from .factories import SubmissionFactory, SubmissionVersionFactory

# ---------------------------------------------------------------------------
# FR-SUB-001: create and edit a submission
# ---------------------------------------------------------------------------


class TestUpsertSubmission:
    def test_creates_a_draft_submission(self, owner, hackathon, team):
        submission = services.upsert_submission(
            actor=owner, hackathon_id=hackathon.id, title="My Project", description="A cool hack.",
        )

        assert submission.team_id == team.id
        assert submission.hackathon_id == hackathon.id
        assert submission.title == "My Project"
        assert submission.submitted_at is not None

    def test_writes_audit_log_on_creation(self, owner, hackathon, team):
        submission = services.upsert_submission(actor=owner, hackathon_id=hackathon.id, title="My Project")
        assert AuditLogEntry.objects.filter(action="submission.created", target_id=str(submission.id)).exists()

    def test_second_call_updates_existing_draft_rather_than_duplicating(self, owner, hackathon, team):
        services.upsert_submission(actor=owner, hackathon_id=hackathon.id, title="My Project")
        services.upsert_submission(actor=owner, hackathon_id=hackathon.id, title="My Project v2")

        assert Submission.objects.filter(team=team).count() == 1
        submission = Submission.objects.get(team=team)
        assert submission.title == "My Project v2"

    def test_any_team_member_can_edit(self, owner, hackathon, team):
        member = AccountFactory()
        AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=member)
        services.upsert_submission(actor=owner, hackathon_id=hackathon.id, title="My Project")

        submission = services.upsert_submission(actor=member, hackathon_id=hackathon.id, title="Edited by member")
        assert submission.title == "Edited by member"

    def test_editing_description_snapshots_previous_version(self, owner, hackathon, team):
        services.upsert_submission(actor=owner, hackathon_id=hackathon.id, title="My Project", description="v1")
        services.upsert_submission(actor=owner, hackathon_id=hackathon.id, title="My Project", description="v2")

        submission = Submission.objects.get(team=team)
        versions = list(SubmissionVersion.objects.filter(submission=submission))
        assert len(versions) == 1
        assert versions[0].description == "v1"

    def test_unchanged_description_does_not_create_a_version(self, owner, hackathon, team):
        services.upsert_submission(actor=owner, hackathon_id=hackathon.id, title="My Project", description="v1")
        services.upsert_submission(actor=owner, hackathon_id=hackathon.id, title="My Project", description="v1")

        assert SubmissionVersion.objects.count() == 0

    def test_only_10_most_recent_versions_are_retained(self, owner, hackathon, team):
        for i in range(12):
            services.upsert_submission(actor=owner, hackathon_id=hackathon.id, title="My Project", description=f"v{i}")

        assert SubmissionVersion.objects.filter(submission__team=team).count() == services.MAX_RETAINED_VERSIONS

    def test_actor_without_a_team_is_rejected(self, hackathon):
        stranger = AccountFactory()
        with pytest.raises(ValidationError):
            services.upsert_submission(actor=stranger, hackathon_id=hackathon.id, title="My Project")

    def test_nonexistent_hackathon_raises_not_found(self, owner):
        with pytest.raises(NotFound):
            services.upsert_submission(actor=owner, hackathon_id=uuid.uuid4(), title="My Project")

    def test_TC_SUB_001a_editing_after_deadline_is_rejected(self, owner):
        with freeze_time("2026-01-01 00:00:00"):
            hackathon = PublishedHackathonFactory(
                submission_opens_at=timezone.now() - timedelta(days=2),
                submission_closes_at=timezone.now() - timedelta(seconds=1),
            )
            RegistrationFactory(user=owner, hackathon=hackathon)
            TeamFactory(hackathon=hackathon, leader_user=owner)

            with pytest.raises(ValidationError):
                services.upsert_submission(actor=owner, hackathon_id=hackathon.id, title="Too Late")


class TestGetMySubmission:
    def test_returns_the_actors_team_submission(self, owner, hackathon, team):
        created = services.upsert_submission(actor=owner, hackathon_id=hackathon.id, title="My Project")

        found = services.get_my_submission(actor=owner, hackathon_id=hackathon.id)
        assert found.id == created.id

    def test_no_submission_yet_raises_not_found(self, owner, hackathon, team):
        with pytest.raises(NotFound):
            services.get_my_submission(actor=owner, hackathon_id=hackathon.id)


# ---------------------------------------------------------------------------
# FR-SUB-002: attach project media
# ---------------------------------------------------------------------------


class TestAttachMedia:
    def test_team_member_can_attach_media(self, owner, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)

        urls = ["https://example.com/a.png", "https://example.com/b.png"]
        result = services.attach_media(actor=owner, submission_id=submission.id, attachment_urls=urls)
        assert result.attachment_urls == urls

    def test_non_member_cannot_attach_media(self, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)
        stranger = AccountFactory()

        with pytest.raises(PermissionDenied):
            services.attach_media(actor=stranger, submission_id=submission.id, attachment_urls=["https://example.com/a.png"])

    def test_TC_SUB_002a_exceeding_5_attachments_is_rejected(self, owner, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)
        urls = [f"https://example.com/{i}.png" for i in range(6)]

        with pytest.raises(ValidationError):
            services.attach_media(actor=owner, submission_id=submission.id, attachment_urls=urls)

    def test_attaching_after_deadline_is_rejected(self, owner, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)
        team.hackathon.submission_closes_at = timezone.now() - timedelta(seconds=1)
        team.hackathon.save(update_fields=["submission_closes_at"])

        with pytest.raises(ValidationError):
            services.attach_media(actor=owner, submission_id=submission.id, attachment_urls=["https://example.com/a.png"])


# ---------------------------------------------------------------------------
# FR-SUB-003: finalize a submission
# ---------------------------------------------------------------------------


class TestFinalizeSubmission:
    def test_finalizing_a_complete_submission_succeeds(self, owner, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)

        result = services.finalize_submission(actor=owner, submission_id=submission.id)
        assert result.is_finalized is True

    def test_writes_audit_log_on_finalize(self, owner, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)
        services.finalize_submission(actor=owner, submission_id=submission.id)
        assert AuditLogEntry.objects.filter(action="submission.finalized", target_id=str(submission.id)).exists()

    def test_finalizing_without_title_is_rejected(self, owner, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon, title="")
        with pytest.raises(ValidationError):
            services.finalize_submission(actor=owner, submission_id=submission.id)

    def test_finalizing_without_any_of_repo_demo_or_media_is_rejected(self, owner, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon, repo_link="", demo_video_url="")
        with pytest.raises(ValidationError):
            services.finalize_submission(actor=owner, submission_id=submission.id)

    def test_demo_video_url_alone_satisfies_the_requirement(self, owner, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon, repo_link="", demo_video_url="https://youtu.be/x")
        result = services.finalize_submission(actor=owner, submission_id=submission.id)
        assert result.is_finalized is True

    def test_still_editable_after_finalizing_before_deadline(self, owner, hackathon, team):
        submission = SubmissionFactory(team=team, hackathon=hackathon)
        services.finalize_submission(actor=owner, submission_id=submission.id)

        updated = services.upsert_submission(actor=owner, hackathon_id=hackathon.id, title="Edited after finalize")
        assert updated.title == "Edited after finalize"

    def test_finalizing_after_deadline_is_rejected(self, owner, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)
        team.hackathon.submission_closes_at = timezone.now() - timedelta(seconds=1)
        team.hackathon.save(update_fields=["submission_closes_at"])

        with pytest.raises(ValidationError):
            services.finalize_submission(actor=owner, submission_id=submission.id)

    def test_non_member_cannot_finalize(self, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)
        stranger = AccountFactory()
        with pytest.raises(PermissionDenied):
            services.finalize_submission(actor=stranger, submission_id=submission.id)


# ---------------------------------------------------------------------------
# View a submission and its history
# ---------------------------------------------------------------------------


class TestGetSubmission:
    def test_team_member_can_view(self, owner, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)
        result = services.get_submission(actor=owner, submission_id=submission.id)
        assert result.id == submission.id

    def test_organizer_can_view(self, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)
        organizer = AccountFactory()
        RoleAssignmentFactory(
            user=organizer, role="organizer", scope_type="hackathon", scope_id=str(team.hackathon_id),
        )
        result = services.get_submission(actor=organizer, submission_id=submission.id)
        assert result.id == submission.id

    def test_outsider_is_denied(self, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)
        stranger = AccountFactory()
        with pytest.raises(PermissionDenied):
            services.get_submission(actor=stranger, submission_id=submission.id)

    def test_nonexistent_submission_raises_not_found(self, owner):
        with pytest.raises(NotFound):
            services.get_submission(actor=owner, submission_id=uuid.uuid4())


class TestGetSubmissionHistory:
    def test_returns_versions_newest_first(self, owner, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)
        with freeze_time(timezone.now() - timedelta(hours=1)):
            older = SubmissionVersionFactory(submission=submission)
        newer = SubmissionVersionFactory(submission=submission)

        _, versions = services.get_submission_history(actor=owner, submission_id=submission.id)
        assert [v.id for v in versions] == [newer.id, older.id]

    def test_outsider_is_denied(self, team):
        submission = SubmissionFactory(team=team, hackathon=team.hackathon)
        stranger = AccountFactory()
        with pytest.raises(PermissionDenied):
            services.get_submission_history(actor=stranger, submission_id=submission.id)


# ---------------------------------------------------------------------------
# FR-JUDGE-004 / Submission track opt-ins
# ---------------------------------------------------------------------------


class TestSubmissionTrackOptIn:
    def test_team_member_can_opt_submission_into_track(self, owner, team):
        submission = SubmissionFactory(
            team=team,
            hackathon=team.hackathon,
        )
        track = ChallengeTrackFactory(
            hackathon=team.hackathon,
        )

        result = services.opt_in_submission_to_track(
            actor=owner,
            submission_id=submission.id,
            track_id=track.id,
        )

        assert result.submission_id == submission.id
        assert result.track_id == track.id

    def test_duplicate_track_opt_in_is_idempotent(self, owner, team):
        submission = SubmissionFactory(
            team=team,
            hackathon=team.hackathon,
        )
        track = ChallengeTrackFactory(
            hackathon=team.hackathon,
        )

        first = services.opt_in_submission_to_track(
            actor=owner,
            submission_id=submission.id,
            track_id=track.id,
        )

        second = services.opt_in_submission_to_track(
            actor=owner,
            submission_id=submission.id,
            track_id=track.id,
        )

        assert first.pk == second.pk
        assert SubmissionTrack.objects.filter(
            submission=submission,
            track=track,
        ).count() == 1

    def test_submission_cannot_opt_into_track_from_another_hackathon(
        self,
        owner,
        team,
    ):
        submission = SubmissionFactory(
            team=team,
            hackathon=team.hackathon,
        )
        other_track = ChallengeTrackFactory()

        with pytest.raises(ValidationError):
            services.opt_in_submission_to_track(
                actor=owner,
                submission_id=submission.id,
                track_id=other_track.id,
            )

    def test_non_team_member_cannot_opt_submission_into_track(self, team):
        submission = SubmissionFactory(
            team=team,
            hackathon=team.hackathon,
        )
        track = ChallengeTrackFactory(
            hackathon=team.hackathon,
        )
        stranger = AccountFactory()

        with pytest.raises(PermissionDenied):
            services.opt_in_submission_to_track(
                actor=stranger,
                submission_id=submission.id,
                track_id=track.id,
            )

    def test_track_opt_in_is_locked_after_submission_deadline(
        self,
        owner,
        team,
    ):
        submission = SubmissionFactory(
            team=team,
            hackathon=team.hackathon,
        )
        track = ChallengeTrackFactory(
            hackathon=team.hackathon,
        )

        team.hackathon.submission_closes_at = (
            timezone.now() - timedelta(seconds=1)
        )
        team.hackathon.save(
            update_fields=["submission_closes_at"],
        )

        with pytest.raises(ValidationError):
            services.opt_in_submission_to_track(
                actor=owner,
                submission_id=submission.id,
                track_id=track.id,
            )

    def test_team_member_can_remove_submission_track_opt_in(
        self,
        owner,
        team,
    ):
        submission = SubmissionFactory(
            team=team,
            hackathon=team.hackathon,
        )
        track = ChallengeTrackFactory(
            hackathon=team.hackathon,
        )

        services.opt_in_submission_to_track(
            actor=owner,
            submission_id=submission.id,
            track_id=track.id,
        )

        services.remove_submission_from_track(
            actor=owner,
            submission_id=submission.id,
            track_id=track.id,
        )

        assert not SubmissionTrack.objects.filter(
            submission=submission,
            track=track,
        ).exists()

    def test_removing_nonexistent_track_opt_in_fails(
        self,
        owner,
        team,
    ):
        submission = SubmissionFactory(
            team=team,
            hackathon=team.hackathon,
        )
        track = ChallengeTrackFactory(
            hackathon=team.hackathon,
        )

        with pytest.raises(NotFound):
            services.remove_submission_from_track(
                actor=owner,
                submission_id=submission.id,
                track_id=track.id,
            )