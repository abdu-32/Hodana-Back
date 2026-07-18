"""
Unit tests against teams/services.py directly (Design Spec Sec 3.1), per
the 80% coverage target in NFR-MAINT-001. Prefer these over HTTP-level
tests for business-rule coverage.
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from freezegun import freeze_time
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.tests.factories import AccountFactory, RoleAssignmentFactory
from apps.core.models import AuditLogEntry
from apps.hackathons.tests.factories import PublishedHackathonFactory
from apps.registrations.tests.factories import RegistrationFactory
from apps.teams import services
from apps.teams.models import Team, TeamMember

from .factories import AcceptedTeamMemberFactory, TeamFactory, TeamMemberFactory

# ---------------------------------------------------------------------------
# FR-TEAM-001: create a team
# ---------------------------------------------------------------------------


class TestCreateTeam:
    def test_creates_team_with_actor_as_leader(self, owner, hackathon, owner_registration):
        team = services.create_team(actor=owner, hackathon_id=hackathon.id, team_name="Byte Busters")

        assert team.hackathon_id == hackathon.id
        assert team.leader_user_id == owner.id
        assert team.team_name == "Byte Busters"

    def test_creator_becomes_first_accepted_member_with_owner_role(self, owner, hackathon, owner_registration):
        team = services.create_team(actor=owner, hackathon_id=hackathon.id, team_name="Byte Busters")

        membership = TeamMember.objects.get(team=team, user=owner)
        assert membership.join_status == "accepted"
        assert membership.role == "owner"

    def test_writes_audit_log_entry(self, owner, hackathon, owner_registration):
        team = services.create_team(actor=owner, hackathon_id=hackathon.id, team_name="Byte Busters")

        assert AuditLogEntry.objects.filter(action="team.created", target_id=str(team.id)).exists()

    def test_snapshots_max_team_size_from_hackathon_rules(self, owner, hackathon, owner_registration):
        hackathon.eligibility_rules = {"min_team_size": 1, "max_team_size": 6}
        hackathon.save(update_fields=["eligibility_rules"])

        team = services.create_team(actor=owner, hackathon_id=hackathon.id, team_name="Byte Busters")
        assert team.max_size == 6

    def test_falls_back_to_default_max_size_when_unconfigured(self, owner, hackathon, owner_registration):
        hackathon.eligibility_rules = None
        hackathon.save(update_fields=["eligibility_rules"])

        team = services.create_team(actor=owner, hackathon_id=hackathon.id, team_name="Byte Busters")
        assert team.max_size == services.DEFAULT_MAX_TEAM_SIZE

    def test_nonexistent_hackathon_raises_not_found(self, owner):
        with pytest.raises(NotFound):
            services.create_team(actor=owner, hackathon_id=uuid.uuid4(), team_name="Byte Busters")

    def test_unregistered_participant_is_rejected(self, hackathon):
        stranger = AccountFactory()
        with pytest.raises(ValidationError):
            services.create_team(actor=stranger, hackathon_id=hackathon.id, team_name="Byte Busters")

    def test_TC_TEAM_001a_second_team_by_same_participant_is_rejected(self, owner, hackathon, owner_registration):
        services.create_team(actor=owner, hackathon_id=hackathon.id, team_name="Byte Busters")

        with pytest.raises(services.ConflictError) as exc_info:
            services.create_team(actor=owner, hackathon_id=hackathon.id, team_name="Second Team")
        assert exc_info.value.status_code == 409

    def test_duplicate_team_name_within_hackathon_is_rejected(self, owner, hackathon, owner_registration):
        services.create_team(actor=owner, hackathon_id=hackathon.id, team_name="Byte Busters")

        other = AccountFactory()
        RegistrationFactory(user=other, hackathon=hackathon)

        with pytest.raises(services.ConflictError):
            services.create_team(actor=other, hackathon_id=hackathon.id, team_name="byte busters")

    def test_same_team_name_allowed_in_different_hackathons(self, owner, hackathon, owner_registration):
        services.create_team(actor=owner, hackathon_id=hackathon.id, team_name="Byte Busters")

        other_hackathon = PublishedHackathonFactory()
        RegistrationFactory(user=owner, hackathon=other_hackathon)

        team = services.create_team(actor=owner, hackathon_id=other_hackathon.id, team_name="Byte Busters")
        assert team.team_name == "Byte Busters"


# ---------------------------------------------------------------------------
# FR-TEAM-002: invite a member
# ---------------------------------------------------------------------------


class TestInviteMember:
    def test_owner_can_invite_registered_participant(self, owner, team, hackathon, mailoutbox):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)

        membership = services.invite_member(actor=owner, team_id=team.id, invitee_email=invitee.email)

        assert membership.join_status == "pending"
        assert membership.user_id == invitee.id
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [invitee.email]

    def test_non_owner_cannot_invite(self, team, hackathon):
        member = AccountFactory()
        AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=member)

        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)

        with pytest.raises(PermissionDenied):
            services.invite_member(actor=member, team_id=team.id, invitee_email=invitee.email)

    def test_inviting_when_team_is_full_is_rejected(self, owner, team, hackathon):
        team.max_size = 1
        team.save(update_fields=["max_size"])

        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)

        with pytest.raises(ValidationError):
            services.invite_member(actor=owner, team_id=team.id, invitee_email=invitee.email)

    def test_inviting_unregistered_email_is_rejected(self, owner, team):
        with pytest.raises(ValidationError):
            services.invite_member(actor=owner, team_id=team.id, invitee_email="nobody@example.com")

    def test_inviting_user_not_registered_for_hackathon_is_rejected(self, owner, team):
        invitee = AccountFactory()  # exists, but never registered for this hackathon
        with pytest.raises(ValidationError):
            services.invite_member(actor=owner, team_id=team.id, invitee_email=invitee.email)

    def test_inviting_user_already_on_a_team_is_rejected(self, owner, team, hackathon):
        other_team = TeamFactory(hackathon=hackathon)
        already_on_team = AccountFactory()
        RegistrationFactory(user=already_on_team, hackathon=hackathon)
        AcceptedTeamMemberFactory(team=other_team, hackathon=hackathon, user=already_on_team)

        with pytest.raises(ValidationError) as exc_info:
            services.invite_member(actor=owner, team_id=team.id, invitee_email=already_on_team.email)
        assert exc_info.value.detail["invitee"]["rule"] == "already_on_team"

    def test_duplicate_pending_invitation_is_rejected(self, owner, team, hackathon):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)

        services.invite_member(actor=owner, team_id=team.id, invitee_email=invitee.email)

        with pytest.raises(services.ConflictError):
            services.invite_member(actor=owner, team_id=team.id, invitee_email=invitee.email)

    def test_invite_is_case_insensitive_on_email(self, owner, team, hackathon, mailoutbox):
        invitee = AccountFactory(email="camelCase@example.com")
        RegistrationFactory(user=invitee, hackathon=hackathon)

        membership = services.invite_member(actor=owner, team_id=team.id, invitee_email="CAMELCASE@example.com")
        assert membership.user_id == invitee.id


# ---------------------------------------------------------------------------
# FR-TEAM-003: accept or decline an invitation
# ---------------------------------------------------------------------------


class TestAcceptInvitation:
    def test_accepting_adds_member_to_roster(self, team, hackathon):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)
        invitation = TeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        membership = services.accept_invitation(actor=invitee, invitation_id=invitation.id)

        assert membership.join_status == "accepted"
        assert membership.role == "member"
        assert membership.responded_at is not None

    def test_accepting_expired_invitation_is_rejected(self, team, hackathon):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)
        invitation = TeamMemberFactory(
            team=team, hackathon=hackathon, user=invitee,
            expires_at=timezone.now() - timedelta(seconds=1),
        )

        with pytest.raises(ValidationError):
            services.accept_invitation(actor=invitee, invitation_id=invitation.id)

    def test_TC_TEAM_003a_accepting_when_team_full_returns_409(self, team, hackathon):
        team.max_size = 1
        team.save(update_fields=["max_size"])

        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)
        invitation = TeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        with pytest.raises(services.ConflictError) as exc_info:
            services.accept_invitation(actor=invitee, invitation_id=invitation.id)
        assert exc_info.value.status_code == 409

        invitation.refresh_from_db()
        assert invitation.join_status == "pending"  # unchanged by the rejected call

    def test_accepting_while_already_on_another_team_in_hackathon_is_rejected(self, team, hackathon):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)
        other_team = TeamFactory(hackathon=hackathon)
        AcceptedTeamMemberFactory(team=other_team, hackathon=hackathon, user=invitee)

        invitation = TeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        with pytest.raises(services.ConflictError):
            services.accept_invitation(actor=invitee, invitation_id=invitation.id)

    def test_accepting_someone_elses_invitation_raises_not_found(self, team, hackathon):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)
        invitation = TeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        stranger = AccountFactory()
        with pytest.raises(NotFound):
            services.accept_invitation(actor=stranger, invitation_id=invitation.id)

    def test_accepting_already_accepted_invitation_is_rejected(self, team, hackathon):
        invitee = AccountFactory()
        RegistrationFactory(user=invitee, hackathon=hackathon)
        invitation = AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        with pytest.raises(ValidationError):
            services.accept_invitation(actor=invitee, invitation_id=invitation.id)


class TestDeclineInvitation:
    def test_declining_sets_status_declined(self, team, hackathon):
        invitee = AccountFactory()
        invitation = TeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        membership = services.decline_invitation(actor=invitee, invitation_id=invitation.id)

        assert membership.join_status == "declined"
        assert membership.responded_at is not None

    def test_declining_twice_is_rejected(self, team, hackathon):
        invitee = AccountFactory()
        invitation = TeamMemberFactory(team=team, hackathon=hackathon, user=invitee)
        services.decline_invitation(actor=invitee, invitation_id=invitation.id)

        with pytest.raises(ValidationError):
            services.decline_invitation(actor=invitee, invitation_id=invitation.id)

    def test_declining_someone_elses_invitation_raises_not_found(self, team, hackathon):
        invitee = AccountFactory()
        invitation = TeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        stranger = AccountFactory()
        with pytest.raises(NotFound):
            services.decline_invitation(actor=stranger, invitation_id=invitation.id)


# ---------------------------------------------------------------------------
# FR-TEAM-004: leave or remove a team member
# ---------------------------------------------------------------------------


class TestLeaveTeam:
    def test_member_leaving_removes_them_from_roster(self, owner, team, hackathon):
        member = AccountFactory()
        AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=member)

        services.leave_team(actor=member, team_id=team.id)

        assert not TeamMember.objects.filter(team=team, user=member).exists()
        team.refresh_from_db()
        assert team.leader_user_id == owner.id  # unaffected

    def test_owner_leaving_transfers_leadership_to_longest_tenured_member(self, owner, team, hackathon):
        with freeze_time(timezone.now() - timedelta(hours=2)):
            earliest = AccountFactory()
            AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=earliest)
        with freeze_time(timezone.now() - timedelta(hours=1)):
            later = AccountFactory()
            AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=later)

        services.leave_team(actor=owner, team_id=team.id)

        team.refresh_from_db()
        assert team.leader_user_id == earliest.id

    def test_last_member_leaving_deletes_the_team(self, owner, team):
        team_id = team.id
        services.leave_team(actor=owner, team_id=team_id)

        assert not Team.objects.filter(id=team_id).exists()

    def test_leaving_writes_audit_log_on_deletion(self, owner, team):
        team_id = team.id
        services.leave_team(actor=owner, team_id=team_id)

        assert AuditLogEntry.objects.filter(action="team.deleted", target_id=str(team_id)).exists()

    def test_TC_TEAM_004a_leaving_after_submission_deadline_is_rejected(self, owner, hackathon):
        with freeze_time("2026-01-01 00:00:00"):
            hackathon.submission_opens_at = timezone.now() - timedelta(days=2)
            hackathon.submission_closes_at = timezone.now() - timedelta(seconds=1)
            hackathon.save(update_fields=["submission_opens_at", "submission_closes_at"])

            team = TeamFactory(hackathon=hackathon, leader_user=owner)
            member = AccountFactory()
            AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=member)

            with pytest.raises(ValidationError):
                services.leave_team(actor=member, team_id=team.id)

    def test_leaving_a_team_you_are_not_on_raises_not_found(self, team):
        stranger = AccountFactory()
        with pytest.raises(NotFound):
            services.leave_team(actor=stranger, team_id=team.id)


class TestRemoveMember:
    def test_owner_can_remove_a_member(self, owner, team, hackathon):
        member = AccountFactory()
        AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=member)

        services.remove_member(actor=owner, team_id=team.id, member_user_id=member.id)

        assert not TeamMember.objects.filter(team=team, user=member).exists()

    def test_non_owner_cannot_remove_a_member(self, team, hackathon):
        member_a = AccountFactory()
        AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=member_a)
        member_b = AccountFactory()
        AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=member_b)

        with pytest.raises(PermissionDenied):
            services.remove_member(actor=member_a, team_id=team.id, member_user_id=member_b.id)

    def test_owner_removing_self_is_rejected(self, owner, team):
        with pytest.raises(ValidationError):
            services.remove_member(actor=owner, team_id=team.id, member_user_id=owner.id)

    def test_removing_after_submission_deadline_is_rejected(self, owner, hackathon):
        with freeze_time("2026-01-01 00:00:00"):
            hackathon.submission_opens_at = timezone.now() - timedelta(days=2)
            hackathon.submission_closes_at = timezone.now() - timedelta(seconds=1)
            hackathon.save(update_fields=["submission_opens_at", "submission_closes_at"])

            team = TeamFactory(hackathon=hackathon, leader_user=owner)
            member = AccountFactory()
            AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=member)

            with pytest.raises(ValidationError):
                services.remove_member(actor=owner, team_id=team.id, member_user_id=member.id)

    def test_removing_nonmember_raises_not_found(self, owner, team):
        stranger = AccountFactory()
        with pytest.raises(NotFound):
            services.remove_member(actor=owner, team_id=team.id, member_user_id=stranger.id)


# ---------------------------------------------------------------------------
# FR-TEAM-005: view team roster
# ---------------------------------------------------------------------------


class TestGetTeamRoster:
    def test_member_can_view_roster(self, owner, team):
        result_team, members = services.get_team_roster(actor=owner, team_id=team.id)
        assert result_team.id == team.id
        assert [m.user_id for m in members] == [owner.id]

    def test_organizer_can_view_roster(self, team, hackathon):
        organizer = AccountFactory()
        RoleAssignmentFactory(
            user=organizer, role="organizer", scope_type="hackathon", scope_id=str(hackathon.id),
        )

        result_team, _ = services.get_team_roster(actor=organizer, team_id=team.id)
        assert result_team.id == team.id

    def test_outsider_is_denied(self, team):
        stranger = AccountFactory()
        with pytest.raises(PermissionDenied):
            services.get_team_roster(actor=stranger, team_id=team.id)

    def test_roster_excludes_pending_invitations(self, owner, team, hackathon):
        pending = AccountFactory()
        TeamMemberFactory(team=team, hackathon=hackathon, user=pending)

        _, members = services.get_team_roster(actor=owner, team_id=team.id)
        assert pending.id not in [m.user_id for m in members]

    def test_nonexistent_team_raises_not_found(self, owner):
        with pytest.raises(NotFound):
            services.get_team_roster(actor=owner, team_id=uuid.uuid4())


# ---------------------------------------------------------------------------
# Owner-facing invitation listing
# ---------------------------------------------------------------------------


class TestListTeamInvitations:
    def test_owner_sees_pending_invitations(self, owner, team, hackathon):
        invitee = AccountFactory()
        TeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        results = list(services.list_team_invitations(actor=owner, team_id=team.id))
        assert len(results) == 1
        assert results[0].user_id == invitee.id

    def test_non_owner_cannot_list_invitations(self, team, hackathon):
        member = AccountFactory()
        AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=member)

        with pytest.raises(PermissionDenied):
            services.list_team_invitations(actor=member, team_id=team.id)


class TestListMyInvitations:
    def test_returns_only_pending_invitations_for_the_actor(self, team, hackathon):
        invitee = AccountFactory()
        TeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        other_team = TeamFactory(hackathon=hackathon)
        other_user = AccountFactory()
        TeamMemberFactory(team=other_team, hackathon=hackathon, user=other_user)

        results = list(services.list_my_invitations(actor=invitee))
        assert len(results) == 1
        assert results[0].user_id == invitee.id

    def test_excludes_declined_and_accepted_invitations(self, team, hackathon):
        invitee = AccountFactory()
        AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        assert list(services.list_my_invitations(actor=invitee)) == []