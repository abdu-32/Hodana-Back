"""
teams -- services

Per Design Spec Sec 3.1: all business logic and cross-model orchestration
lives here. This is the layer that enforces the business rules from
Document 02 Sec 3.7 (TEAM module) and BR-001/BR-003.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from apps.accounts.models import Account, RoleAssignment
from apps.core.models import AuditLogEntry
from apps.hackathons.models import Hackathon
from apps.notifications.services import notify_invitation_response, notify_team_invitation
from apps.registrations.models import Registration

from .models import Team, TeamJoinRequest, TeamMember

DEFAULT_MAX_TEAM_SIZE = 4
INVITATION_EXPIRY_DAYS = 7


class ConflictError(APIException):
    """HTTP 409 -- e.g. FR-TEAM-001/BR-001's 'already on a team' case."""
    status_code = 409
    default_detail = "This action conflicts with the current state of the team."
    default_code = "conflict"


def _get_hackathon_or_404(hackathon_id):
    try:
        return Hackathon.objects.get(id=hackathon_id)
    except (Hackathon.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound("Hackathon not found.")


def _get_team_or_404(team_id):
    try:
        return Team.objects.select_related("hackathon", "leader_user").get(id=team_id)
    except (Team.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound("Team not found.")


def _get_invitation_or_404(*, actor, invitation_id):
    try:
        return TeamMember.objects.select_related("team", "team__hackathon").get(
            id=invitation_id, user=actor,
        )
    except (TeamMember.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound("Invitation not found.")


def _accepted_member_count(team):
    return TeamMember.objects.filter(team=team, join_status="accepted").count()


def _has_accepted_team_in_hackathon(*, hackathon, user):
    """BR-001: a participant may belong to only one team per hackathon."""
    return TeamMember.objects.filter(
        hackathon=hackathon, user=user, join_status="accepted",
    ).exists()


def _require_active_registration(*, hackathon, user):
    if not Registration.objects.filter(
        hackathon=hackathon, user=user, withdrawn_at__isnull=True,
    ).exists():
        raise ValidationError("You must be registered for this hackathon to do that.")


def _require_roster_not_locked(team):
    """BR-003: submissions, team rosters, and track opt-ins become
    read-only immediately at the configured submission deadline."""
    if timezone.now() >= team.hackathon.submission_closes_at:
        raise ValidationError("Team rosters are locked after the submission deadline.")


# ---- FR-TEAM-001: create a team ---------------------------------------------

def create_team(*, actor, hackathon_id, team_name, description=""):
    hackathon = _get_hackathon_or_404(hackathon_id)

    _require_active_registration(hackathon=hackathon, user=actor)

    if _has_accepted_team_in_hackathon(hackathon=hackathon, user=actor):
        raise ConflictError("You already belong to a team in this hackathon.")

    clean_name = team_name.strip()
    if Team.objects.filter(hackathon=hackathon, team_name__iexact=clean_name).exists():
        raise ConflictError("A team with this name already exists in this hackathon.")

    max_size = (hackathon.eligibility_rules or {}).get("max_team_size") or DEFAULT_MAX_TEAM_SIZE

    with transaction.atomic():
        team = Team.objects.create(
            hackathon=hackathon,
            team_name=clean_name,
            description=description.strip() if description else "",
            leader_user=actor,
            max_size=max_size,
        )
        TeamMember.objects.create(
            team=team,
            hackathon=hackathon,
            user=actor,
            invitee_email=actor.email,
            join_status="accepted",
            expires_at=timezone.now() + timedelta(days=365),
            responded_at=timezone.now(),
        )
        # Cancel any pending invitations or join requests for this user in this hackathon
        TeamMember.objects.filter(hackathon=hackathon, user=actor, join_status="pending").delete()
        TeamJoinRequest.objects.filter(hackathon=hackathon, user=actor, status="pending").update(status="cancelled")

        AuditLogEntry.objects.create(
            actor_id=actor.id, action="team.created", target_type="team", target_id=str(team.id),
        )

    return team


def update_team(*, actor, team_id, team_name=None, description=None, open_to_members=None):
    team = _get_team_or_404(team_id)

    if team.leader_user_id != actor.id:
        raise PermissionDenied("Only the team leader can edit team settings.")

    _require_roster_not_locked(team)

    fields_to_update = []

    if team_name is not None:
        clean_name = team_name.strip()
        if clean_name and clean_name.lower() != team.team_name.lower():
            if Team.objects.filter(hackathon=team.hackathon, team_name__iexact=clean_name).exclude(id=team.id).exists():
                raise ConflictError("A team with this name already exists in this hackathon.")
            team.team_name = clean_name
            fields_to_update.append("team_name")

    if description is not None:
        team.description = description.strip()
        fields_to_update.append("description")

    if open_to_members is not None:
        team.open_to_members = bool(open_to_members)
        fields_to_update.append("open_to_members")

    if fields_to_update:
        team.save(update_fields=fields_to_update)

    return team


def delete_team(*, actor, team_id):
    team = _get_team_or_404(team_id)

    if team.leader_user_id != actor.id:
        raise PermissionDenied("Only the team leader can delete the team.")

    _require_roster_not_locked(team)

    with transaction.atomic():
        deleted_id = team.id
        team.delete()
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="team.deleted", target_type="team", target_id=str(deleted_id),
        )


# ---- FR-TEAM-002: invite a member -------------------------------------------

def invite_member(*, actor, team_id, invitee_email):
    team = _get_team_or_404(team_id)

    if team.leader_user_id != actor.id:
        raise PermissionDenied("Only the team leader can invite members.")

    _require_roster_not_locked(team)

    if _accepted_member_count(team) >= team.max_size:
        raise ValidationError("This team has already reached its maximum size.")

    clean_email = invitee_email.strip().lower()
    try:
        invitee = Account.objects.get(email__iexact=clean_email)
    except Account.DoesNotExist:
        raise ValidationError({"inviteeEmail": ["No registered user found with this email."]})

    if invitee.id == actor.id:
        raise ValidationError({"inviteeEmail": ["You cannot invite yourself."]})

    _require_active_registration(hackathon=team.hackathon, user=invitee)

    if _has_accepted_team_in_hackathon(hackathon=team.hackathon, user=invitee):
        raise ValidationError({
            "invitee": {
                "rule": "already_on_team",
                "message": "This user already belongs to a team in this hackathon.",
            },
        })

    if TeamMember.objects.filter(team=team, user=invitee, join_status="pending").exists():
        raise ConflictError("This user already has a pending invitation to this team.")

    now = timezone.now()
    membership = TeamMember.objects.create(
        team=team,
        hackathon=team.hackathon,
        user=invitee,
        invitee_email=invitee.email,
        join_status="pending",
        expires_at=now + timedelta(days=INVITATION_EXPIRY_DAYS),
    )

    notify_team_invitation(membership)
    return membership


def cancel_invitation(*, actor, invitation_id):
    try:
        invitation = TeamMember.objects.select_related("team").get(
            id=invitation_id, join_status="pending"
        )
    except (TeamMember.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound("Invitation not found.")

    if invitation.team.leader_user_id != actor.id:
        raise PermissionDenied("Only the team leader can cancel this invitation.")

    invitation.delete()


def list_team_invitations(*, actor, team_id):
    team = _get_team_or_404(team_id)
    if team.leader_user_id != actor.id:
        raise PermissionDenied("Only the team leader can view pending invitations.")

    return (
        TeamMember.objects.filter(team=team, join_status="pending")
        .select_related("user")
        .order_by("-invited_at")
    )


def list_my_invitations(*, actor, hackathon_id=None):
    qs = TeamMember.objects.filter(user=actor, join_status="pending").select_related("team", "team__hackathon", "team__leader_user")
    if hackathon_id:
        qs = qs.filter(hackathon_id=hackathon_id)
    return qs.order_by("-invited_at")


# ---- FR-TEAM-003: accept or decline an invitation ---------------------------

def decline_invitation(*, actor, invitation_id):
    membership = _get_invitation_or_404(actor=actor, invitation_id=invitation_id)

    if membership.join_status != "pending":
        raise ValidationError("This invitation is no longer pending.")

    membership.join_status = "declined"
    membership.responded_at = timezone.now()
    membership.save(update_fields=["join_status", "responded_at"])

    notify_invitation_response(membership)
    return membership


def accept_invitation(*, actor, invitation_id):
    membership = _get_invitation_or_404(actor=actor, invitation_id=invitation_id)

    if membership.join_status != "pending":
        raise ValidationError("This invitation is no longer pending.")

    if membership.expires_at < timezone.now():
        raise ValidationError("This invitation has expired.")

    with transaction.atomic():
        team = Team.objects.select_for_update().select_related("hackathon").get(id=membership.team_id)
        _require_roster_not_locked(team)

        if _accepted_member_count(team) >= team.max_size:
            raise ConflictError("This team is full.")

        if _has_accepted_team_in_hackathon(hackathon=team.hackathon, user=actor):
            raise ConflictError("You already belong to a team in this hackathon.")

        membership.join_status = "accepted"
        membership.responded_at = timezone.now()
        membership.save(update_fields=["join_status", "responded_at"])

        # Cancel other pending invites & join requests for this user in this hackathon
        TeamMember.objects.filter(hackathon=team.hackathon, user=actor, join_status="pending").exclude(id=membership.id).delete()
        TeamJoinRequest.objects.filter(hackathon=team.hackathon, user=actor, status="pending").update(status="cancelled")

        AuditLogEntry.objects.create(
            actor_id=actor.id, action="team.member_joined",
            target_type="team", target_id=str(team.id),
        )

    notify_invitation_response(membership)
    return membership


# ---- Join Requests (Looking for a Team discovery flow) ----------------------

def create_join_request(*, actor, team_id, message=""):
    team = _get_team_or_404(team_id)

    _require_active_registration(hackathon=team.hackathon, user=actor)
    _require_roster_not_locked(team)

    if not team.open_to_members:
        raise ValidationError("This team is currently not accepting new members.")

    if _accepted_member_count(team) >= team.max_size:
        raise ConflictError("This team has already reached its maximum capacity.")

    if _has_accepted_team_in_hackathon(hackathon=team.hackathon, user=actor):
        raise ConflictError("You already belong to a team in this hackathon.")

    if TeamJoinRequest.objects.filter(team=team, user=actor, status="pending").exists():
        raise ConflictError("You already have a pending join request for this team.")

    join_request = TeamJoinRequest.objects.create(
        team=team,
        hackathon=team.hackathon,
        user=actor,
        message=message.strip() if message else "",
        status="pending",
    )
    return join_request


def cancel_join_request(*, actor, request_id):
    try:
        join_request = TeamJoinRequest.objects.get(id=request_id, user=actor, status="pending")
    except (TeamJoinRequest.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound("Join request not found.")

    join_request.status = "cancelled"
    join_request.save(update_fields=["status"])
    return join_request


def review_join_request(*, actor, request_id, decision):
    try:
        join_request = TeamJoinRequest.objects.select_related("team", "team__hackathon", "user").get(
            id=request_id, status="pending"
        )
    except (TeamJoinRequest.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound("Join request not found.")

    team = join_request.team
    if team.leader_user_id != actor.id:
        raise PermissionDenied("Only the team leader can review join requests.")

    _require_roster_not_locked(team)

    if decision == "rejected":
        join_request.status = "rejected"
        join_request.responded_at = timezone.now()
        join_request.save(update_fields=["status", "responded_at"])
        return join_request

    # Decision == "accepted"
    with transaction.atomic():
        team = Team.objects.select_for_update().get(id=team.id)
        if _accepted_member_count(team) >= team.max_size:
            raise ConflictError("This team is already full.")

        if _has_accepted_team_in_hackathon(hackathon=team.hackathon, user=join_request.user):
            join_request.status = "rejected"
            join_request.responded_at = timezone.now()
            join_request.save(update_fields=["status", "responded_at"])
            raise ConflictError("This participant already joined another team in this hackathon.")

        join_request.status = "accepted"
        join_request.responded_at = timezone.now()
        join_request.save(update_fields=["status", "responded_at"])

        TeamMember.objects.create(
            team=team,
            hackathon=team.hackathon,
            user=join_request.user,
            invitee_email=join_request.user.email,
            join_status="accepted",
            expires_at=timezone.now() + timedelta(days=365),
            responded_at=timezone.now(),
        )

        # Cancel other pending invites & requests for that user
        TeamMember.objects.filter(hackathon=team.hackathon, user=join_request.user, join_status="pending").delete()
        TeamJoinRequest.objects.filter(hackathon=team.hackathon, user=join_request.user, status="pending").update(status="cancelled")

        AuditLogEntry.objects.create(
            actor_id=actor.id, action="team.member_joined",
            target_type="team", target_id=str(team.id),
            metadata={"via": "join_request", "user_id": str(join_request.user_id)},
        )

    return join_request


def list_team_join_requests(*, actor, team_id):
    team = _get_team_or_404(team_id)
    if team.leader_user_id != actor.id:
        raise PermissionDenied("Only the team leader can view join requests.")

    return (
        TeamJoinRequest.objects.filter(team=team, status="pending")
        .select_related("user")
        .order_by("-created_at")
    )


# ---- FR-TEAM-004: leave or remove a team member -----------------------------

def _detach_member(*, team, membership, actor_id):
    was_leader = membership.user_id == team.leader_user_id
    membership.delete()

    remaining = list(
        TeamMember.objects.filter(team=team, join_status="accepted").order_by("responded_at", "invited_at")
    )

    if not remaining:
        team_id = team.id
        team.delete()
        AuditLogEntry.objects.create(
            actor_id=actor_id, action="team.deleted", target_type="team", target_id=str(team_id),
        )
        return

    if was_leader:
        new_leader = remaining[0]
        team.leader_user = new_leader.user
        team.save(update_fields=["leader_user"])
        AuditLogEntry.objects.create(
            actor_id=actor_id, action="team.leadership_transferred",
            target_type="team", target_id=str(team.id),
            metadata={"new_leader_id": str(new_leader.user_id)},
        )


def leave_team(*, actor, team_id):
    team = _get_team_or_404(team_id)

    try:
        membership = TeamMember.objects.get(team=team, user=actor, join_status="accepted")
    except TeamMember.DoesNotExist:
        raise NotFound("You are not an active member of this team.")

    _require_roster_not_locked(team)

    with transaction.atomic():
        _detach_member(team=team, membership=membership, actor_id=actor.id)


def remove_member(*, actor, team_id, member_user_id):
    team = _get_team_or_404(team_id)

    if team.leader_user_id != actor.id:
        raise PermissionDenied("Only the team leader can remove members.")

    if str(member_user_id) == str(actor.id):
        raise ValidationError("Use the leave team action to leave.")

    try:
        membership = TeamMember.objects.get(team=team, user_id=member_user_id, join_status="accepted")
    except (TeamMember.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound("Member not found on this team.")

    _require_roster_not_locked(team)

    with transaction.atomic():
        _detach_member(team=team, membership=membership, actor_id=actor.id)


def remove_member_from_all_teams(*, hackathon, user):
    with transaction.atomic():
        accepted_memberships = list(
            TeamMember.objects.select_related("team").filter(
                hackathon=hackathon, user=user, join_status="accepted",
            )
        )
        for membership in accepted_memberships:
            _detach_member(team=membership.team, membership=membership, actor_id=user.id)

        TeamMember.objects.filter(
            hackathon=hackathon, user=user, join_status="pending",
        ).delete()
        TeamJoinRequest.objects.filter(
            hackathon=hackathon, user=user, status="pending",
        ).update(status="cancelled")


# ---- FR-TEAM-005: view team roster & hackathon discovery -------------------

def get_team_roster(*, actor, team_id):
    team = _get_team_or_404(team_id)

    is_member = TeamMember.objects.filter(team=team, user=actor, join_status="accepted").exists()
    is_organizer = (
        RoleAssignment.objects.filter(
            user=actor, role="organizer", scope_type="organization", scope_id=team.hackathon.host_org_id,
        ).exists()
        or RoleAssignment.objects.filter(
            user=actor, role="organizer", scope_type="hackathon", scope_id=team.hackathon_id,
        ).exists()
        or team.hackathon.created_by_id == actor.id
    )
    is_platform_admin = getattr(actor, "is_platform_admin", False)

    if not (is_member or is_organizer or is_platform_admin):
        raise PermissionDenied("You do not have permission to view this team's private roster.")

    members = (
        TeamMember.objects.filter(team=team, join_status="accepted")
        .select_related("user")
        .order_by("responded_at")
    )
    return team, members


def list_hackathon_teams(*, actor, hackathon_id):
    hackathon = _get_hackathon_or_404(hackathon_id)
    return Team.objects.filter(hackathon=hackathon).select_related("leader_user", "hackathon").order_by("-created_at")


def get_hackathon_team_state(*, actor, hackathon_id):
    """Unified state endpoint providing everything a participant needs
    for the Team tab of a specific hackathon."""
    hackathon = _get_hackathon_or_404(hackathon_id)

    # 1. Registration
    try:
        registration = Registration.objects.get(
            hackathon=hackathon, user=actor, withdrawn_at__isnull=True
        )
    except Registration.DoesNotExist:
        registration = None

    # 2. Active Team Membership
    my_membership = (
        TeamMember.objects.filter(hackathon=hackathon, user=actor, join_status="accepted")
        .select_related("team", "team__leader_user", "team__hackathon")
        .first()
    )

    team = my_membership.team if my_membership else None
    members = []
    pending_invitations = []
    pending_join_requests = []

    if team:
        members = list(
            TeamMember.objects.filter(team=team, join_status="accepted")
            .select_related("user")
            .order_by("responded_at")
        )
        if team.leader_user_id == actor.id:
            pending_invitations = list(
                TeamMember.objects.filter(team=team, join_status="pending")
                .select_related("user")
                .order_by("-invited_at")
            )
            pending_join_requests = list(
                TeamJoinRequest.objects.filter(team=team, status="pending")
                .select_related("user")
                .order_by("-created_at")
            )

    # 3. Sent Join Requests
    my_sent_requests = list(
        TeamJoinRequest.objects.filter(hackathon=hackathon, user=actor, status="pending")
        .select_related("team", "team__leader_user")
        .order_by("-created_at")
    )

    # 4. Received Invitations
    my_invitations = list(
        TeamMember.objects.filter(hackathon=hackathon, user=actor, join_status="pending")
        .select_related("team", "team__leader_user", "team__hackathon")
        .order_by("-invited_at")
    )

    # 5. Open Teams for discovery
    open_teams = list(
        Team.objects.filter(hackathon=hackathon, open_to_members=True)
        .select_related("leader_user", "hackathon")
        .order_by("-created_at")
    )

    return {
        "hackathon": hackathon,
        "registration": registration,
        "team": team,
        "is_leader": bool(team and team.leader_user_id == actor.id),
        "members": members,
        "pending_invitations": pending_invitations,
        "pending_join_requests": pending_join_requests,
        "my_sent_requests": my_sent_requests,
        "my_invitations": my_invitations,
        "open_teams": open_teams,
    }