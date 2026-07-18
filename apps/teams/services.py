"""
teams -- services

Per Design Spec Sec 3.1: all business logic and cross-model orchestration
lives here. This is the layer that enforces the business rules from
Document 02 Sec 3.7 (TEAM module) and BR-001/BR-003, and is unit-tested
directly (NFR-MAINT-001: 80% coverage target) without spinning up HTTP
requests.
"""

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from apps.accounts.models import Account, RoleAssignment
from apps.core.models import AuditLogEntry
from apps.hackathons.models import Hackathon
from apps.registrations.models import Registration

from .models import Team, TeamMember

# FR-HACK-003 lets an Organizer configure eligibility_rules.max_team_size,
# but that key is optional (Doc 02 doesn't mandate it be set before
# publish). This is the fallback used at team-creation time when a
# hackathon has no max_team_size configured, so FR-TEAM-001 always has a
# concrete, positive value to snapshot onto team.max_size.
DEFAULT_MAX_TEAM_SIZE = 4

# DB Design Sec 4.5: "expires_at ... invited_at + 7 days, per FR-TEAM-002."
INVITATION_EXPIRY_DAYS = 7


class ConflictError(APIException):
    """HTTP 409 -- e.g. FR-TEAM-001/BR-001's 'already on a team' case, or
    FR-TEAM-003's 'team is full' race-condition acceptance criterion."""
    status_code = 409
    default_detail = "This action conflicts with the current state of the team."
    default_code = "conflict"


def _send_mail(*, subject, message, to):
    """Single seam to swap for a Celery task later. Synchronous for now,
    same pattern as apps.registrations.services._send_mail -- apps.notifications
    is still an unimplemented stub."""
    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[to],
        fail_silently=False,
    )


def _get_hackathon_or_404(hackathon_id):
    try:
        return Hackathon.objects.get(id=hackathon_id)
    except (Hackathon.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _get_team_or_404(team_id):
    try:
        return Team.objects.select_related("hackathon").get(id=team_id)
    except (Team.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _get_invitation_or_404(*, actor, invitation_id):
    """Scoped to the requesting user, same 'not found rather than 403'
    reasoning as registrations._get_registration_or_404 -- an invitation
    addressed to someone else simply isn't a row this actor can see."""
    try:
        return TeamMember.objects.select_related("team", "team__hackathon").get(
            id=invitation_id, user=actor,
        )
    except (TeamMember.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


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

def create_team(*, actor, hackathon_id, team_name):
    hackathon = _get_hackathon_or_404(hackathon_id)

    _require_active_registration(hackathon=hackathon, user=actor)

    # BR-001: "Attempting to create a second team within the same
    # hackathon by a participant who already belongs to one is rejected."
    if _has_accepted_team_in_hackathon(hackathon=hackathon, user=actor):
        raise ConflictError("You already belong to a team in this hackathon.")

    if Team.objects.filter(hackathon=hackathon, team_name__iexact=team_name).exists():
        raise ConflictError("A team with this name already exists in this hackathon.")

    max_size = (hackathon.eligibility_rules or {}).get("max_team_size") or DEFAULT_MAX_TEAM_SIZE

    with transaction.atomic():
        team = Team.objects.create(
            hackathon=hackathon, team_name=team_name, leader_user=actor, max_size=max_size,
        )
        # FR-TEAM-001: "The creator is automatically added as the first
        # team member with role Owner." (role is derived, see models.py)
        TeamMember.objects.create(
            team=team, hackathon=hackathon, user=actor, invitee_email=actor.email,
            join_status="accepted", expires_at=timezone.now(), responded_at=timezone.now(),
        )
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="team.created", target_type="team", target_id=str(team.id),
        )

    return team


# ---- FR-TEAM-002: invite a member -------------------------------------------

def invite_member(*, actor, team_id, invitee_email):
    team = _get_team_or_404(team_id)

    if team.leader_user_id != actor.id:
        raise PermissionDenied("Only the team owner can invite members.")

    if _accepted_member_count(team) >= team.max_size:
        raise ValidationError("This team has already reached its maximum size.")

    try:
        invitee = Account.objects.get(email__iexact=invitee_email)
    except Account.DoesNotExist:
        raise ValidationError({"inviteeEmail": ["No registered user found with this email."]})

    _require_active_registration(hackathon=team.hackathon, user=invitee)

    # BR-001: "Inviting a user who already belongs to a team in the same
    # hackathon is rejected ... with a specific error."
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
        team=team, hackathon=team.hackathon, user=invitee, invitee_email=invitee.email,
        join_status="pending", expires_at=now + timedelta(days=INVITATION_EXPIRY_DAYS),
    )

    _send_mail(
        subject=f"You've been invited to join {team.team_name}",
        message=(
            f"{actor.full_name} invited you to join the team \"{team.team_name}\" "
            f"for {team.hackathon.title}."
        ),
        to=invitee.contact_email or invitee.email,
    )

    return membership


def list_team_invitations(*, actor, team_id):
    """Pending invitations for a team -- owner-only, not part of the
    public roster (FR-TEAM-005 scopes the roster itself, this is a
    supporting view for the owner to manage outstanding invites)."""
    team = _get_team_or_404(team_id)
    if team.leader_user_id != actor.id:
        raise PermissionDenied("Only the team owner can view pending invitations.")

    return (
        TeamMember.objects.filter(team=team, join_status="pending")
        .select_related("user")
        .order_by("-invited_at")
    )


def list_my_invitations(*, actor):
    return (
        TeamMember.objects.filter(user=actor, join_status="pending")
        .select_related("team", "team__hackathon")
        .order_by("-invited_at")
    )


# ---- FR-TEAM-003: accept or decline an invitation ---------------------------

def decline_invitation(*, actor, invitation_id):
    membership = _get_invitation_or_404(actor=actor, invitation_id=invitation_id)

    if membership.join_status != "pending":
        raise ValidationError("This invitation is no longer pending.")

    membership.join_status = "declined"
    membership.responded_at = timezone.now()
    membership.save(update_fields=["join_status", "responded_at"])
    return membership


def accept_invitation(*, actor, invitation_id):
    membership = _get_invitation_or_404(actor=actor, invitation_id=invitation_id)

    if membership.join_status != "pending":
        raise ValidationError("This invitation is no longer pending.")

    if membership.expires_at < timezone.now():
        raise ValidationError("This invitation has expired.")

    with transaction.atomic():
        # Design Spec Sec 5.1: SELECT ... FOR UPDATE on the team row so
        # two concurrent acceptances can't both pass the capacity check.
        team = Team.objects.select_for_update().select_related("hackathon").get(id=membership.team_id)

        if _accepted_member_count(team) >= team.max_size:
            # FR-TEAM-003: "the invitation reverts to pending for Owner
            # re-action" -- it already is pending, so this is a no-op on
            # membership itself; surface the 409 to the caller.
            raise ConflictError("This team is full.")

        if _has_accepted_team_in_hackathon(hackathon=team.hackathon, user=actor):
            raise ConflictError("You already belong to a team in this hackathon.")

        membership.join_status = "accepted"
        membership.responded_at = timezone.now()
        membership.save(update_fields=["join_status", "responded_at"])

        AuditLogEntry.objects.create(
            actor_id=actor.id, action="team.member_joined",
            target_type="team", target_id=str(team.id),
        )

    return membership


# ---- FR-TEAM-004: leave or remove a team member -----------------------------

def _detach_member(*, team, membership, actor_id):
    """Shared by leave_team and remove_member. Deletes the roster row and
    handles the two special cases from FR-TEAM-004:
    - Owner leaving with members remaining -> ownership transfers to the
      longest-tenured remaining member.
    - Last member leaving -> the team is deleted.
    """
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
        raise NotFound()

    _require_roster_not_locked(team)

    with transaction.atomic():
        _detach_member(team=team, membership=membership, actor_id=actor.id)


def remove_member(*, actor, team_id, member_user_id):
    team = _get_team_or_404(team_id)

    if team.leader_user_id != actor.id:
        raise PermissionDenied("Only the team owner can remove members.")

    if str(member_user_id) == str(actor.id):
        raise ValidationError("Use the leave-team action to remove yourself.")

    try:
        membership = TeamMember.objects.get(team=team, user_id=member_user_id, join_status="accepted")
    except (TeamMember.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()

    _require_roster_not_locked(team)

    with transaction.atomic():
        _detach_member(team=team, membership=membership, actor_id=actor.id)


# ---- FR-TEAM-005: view team roster ------------------------------------------

def get_team_roster(*, actor, team_id):
    """Preconditions: the requester is a team member or the hackathon's
    Organizer. A user who is neither receives HTTP 403 (via
    PermissionDenied)."""
    team = _get_team_or_404(team_id)

    is_member = TeamMember.objects.filter(team=team, user=actor, join_status="accepted").exists()
    is_organizer = RoleAssignment.objects.filter(
        user=actor, role="organizer", scope_type="hackathon", scope_id=team.hackathon_id,
    ).exists()
    is_platform_admin = getattr(actor, "is_platform_admin", False)

    if not (is_member or is_organizer or is_platform_admin):
        raise PermissionDenied()

    members = (
        TeamMember.objects.filter(team=team, join_status="accepted")
        .select_related("user")
        .order_by("responded_at")
    )
    return team, members