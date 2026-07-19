"""
submissions -- services

Per Design Spec Sec 3.1: all business logic and cross-model orchestration
lives here. This is the layer that enforces the business rules from
Document 02 Sec 3.8 (SUB module) and BR-003/BR-006, and is unit-tested
directly (NFR-MAINT-001: 80% coverage target) without spinning up HTTP
requests.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import RoleAssignment
from apps.core.models import AuditLogEntry
from apps.hackathons.models import Hackathon
from apps.teams.models import TeamMember

from .models import Submission, SubmissionVersion

# FR-SUB-002: "up to 5 media files (images or a single demo video link)".
MAX_ATTACHMENTS = 5

# FR-SUB-004: "up to the 10 most recent versions are retained".
MAX_RETAINED_VERSIONS = 10


def _get_hackathon_or_404(hackathon_id):
    try:
        return Hackathon.objects.get(id=hackathon_id)
    except (Hackathon.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _get_submission_or_404(submission_id):
    try:
        return Submission.objects.select_related("hackathon", "team").get(id=submission_id)
    except (Submission.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _get_actor_team(*, hackathon, actor):
    """FR-SUB-001: "any team member" may create/edit -- resolves the
    actor's own accepted team within this hackathon. A team is a
    precondition for having a submission at all (FR-SUB-001's own
    "team is registered for the hackathon" precondition), so a user with
    no team here gets a 400, same as teams._require_active_registration's
    reasoning for a missing precondition rather than a 403/404."""
    try:
        membership = TeamMember.objects.select_related("team").get(
            hackathon=hackathon, user=actor, join_status="accepted",
        )
    except TeamMember.DoesNotExist:
        raise ValidationError("You must belong to a team in this hackathon to have a submission.")
    return membership.team


def _is_team_member(*, team, actor):
    return TeamMember.objects.filter(team=team, user=actor, join_status="accepted").exists()


def _is_organizer_or_admin(*, hackathon, actor):
    if getattr(actor, "is_platform_admin", False):
        return True
    return RoleAssignment.objects.filter(
        user=actor, role="organizer", scope_type="hackathon", scope_id=hackathon.id,
    ).exists()


def _require_team_member(*, submission, actor):
    if not _is_team_member(team=submission.team, actor=actor):
        raise PermissionDenied()


def _require_team_member_or_organizer(*, submission, actor):
    """FR-SUB-004: version history is visible only to team members and
    the Organizer -- reused for the submission-detail view too, since
    Doc 02 never opens either endpoint beyond that pair (public/judge
    visibility of a submission's *contents* is a separate concern owned
    by apps.showcase / apps.judging once they read this model directly)."""
    if _is_team_member(team=submission.team, actor=actor):
        return
    if _is_organizer_or_admin(hackathon=submission.hackathon, actor=actor):
        return
    raise PermissionDenied()


def _require_not_locked(hackathon):
    """BR-003: submissions become read-only immediately at the submission
    deadline. Checked live against the hackathon's deadline, same pattern
    as apps.teams.services._require_roster_not_locked -- the
    Celery-Beat-driven `locked_at` write described in Design Spec Sec 5.2
    is a supporting/notification job, not the source of truth for this
    check."""
    if timezone.now() >= hackathon.submission_closes_at:
        raise ValidationError("Submissions are locked after the submission deadline.")


def _record_version(*, submission, actor):
    """Snapshots the pre-change title/description, then trims to the 10
    most recently retained versions (FR-SUB-004)."""
    SubmissionVersion.objects.create(
        submission=submission, title=submission.title, description=submission.description, edited_by=actor,
    )
    stale_ids = list(
        SubmissionVersion.objects.filter(submission=submission)
        .order_by("-created_at")
        .values_list("id", flat=True)[MAX_RETAINED_VERSIONS:]
    )
    if stale_ids:
        SubmissionVersion.objects.filter(id__in=stale_ids).delete()


# ---- FR-SUB-001: create and edit a submission -------------------------------

def upsert_submission(*, actor, hackathon_id, title, tagline="", description="", technologies=None, repo_link="", demo_video_url=""):
    hackathon = _get_hackathon_or_404(hackathon_id)
    team = _get_actor_team(hackathon=hackathon, actor=actor)
    _require_not_locked(hackathon)

    technologies = technologies or []

    with transaction.atomic():
        # select_for_update: two team members saving concurrently should
        # not race past each other's version snapshot.
        submission = Submission.objects.select_for_update().filter(team=team).first()

        if submission is None:
            submission = Submission.objects.create(
                hackathon=hackathon, team=team, title=title, tagline=tagline, description=description,
                technologies=technologies, repo_link=repo_link, demo_video_url=demo_video_url,
                submitted_at=timezone.now(),
            )
            AuditLogEntry.objects.create(
                actor_id=actor.id, action="submission.created", target_type="submission",
                target_id=str(submission.id),
            )
            return submission

        # FR-SUB-001: "a second creation attempt updates the existing
        # draft rather than creating a duplicate."
        if submission.title != title or submission.description != description:
            _record_version(submission=submission, actor=actor)

        submission.title = title
        submission.tagline = tagline
        submission.description = description
        submission.technologies = technologies
        submission.repo_link = repo_link
        submission.demo_video_url = demo_video_url
        submission.save(update_fields=[
            "title", "tagline", "description", "technologies", "repo_link", "demo_video_url", "updated_at",
        ])

    return submission


def get_my_submission(*, actor, hackathon_id):
    """GET /submissions/hackathons/{hackathonId}/me -- convenience lookup
    so a team can tell whether a draft already exists before calling the
    upsert endpoint."""
    hackathon = _get_hackathon_or_404(hackathon_id)
    team = _get_actor_team(hackathon=hackathon, actor=actor)
    try:
        return Submission.objects.get(team=team)
    except Submission.DoesNotExist:
        raise NotFound()


# ---- FR-SUB-002: attach project media ---------------------------------------

def attach_media(*, actor, submission_id, attachment_urls):
    submission = _get_submission_or_404(submission_id)
    _require_team_member(submission=submission, actor=actor)
    _require_not_locked(submission.hackathon)

    if len(attachment_urls) > MAX_ATTACHMENTS:
        raise ValidationError({"attachmentUrls": [f"A submission may have at most {MAX_ATTACHMENTS} attachments."]})

    submission.attachment_urls = attachment_urls
    submission.save(update_fields=["attachment_urls", "updated_at"])
    return submission


# ---- FR-SUB-003: finalize a submission --------------------------------------

def finalize_submission(*, actor, submission_id):
    submission = _get_submission_or_404(submission_id)
    _require_team_member(submission=submission, actor=actor)
    _require_not_locked(submission.hackathon)

    # FR-SUB-003 precondition: "the submission has all required fields
    # (FR-SUB-001)" -- title, description, and at least one of
    # {repo_link, demo_video_url, attachment_urls}. See models.py's
    # module docstring for why this is checked here, not at draft-save.
    errors = {}
    if not submission.title:
        errors["title"] = ["Title is required to finalize a submission."]
    if not submission.description:
        errors["description"] = ["Description is required to finalize a submission."]
    if not (submission.repo_link or submission.demo_video_url or submission.attachment_urls):
        errors["repoLink"] = ["At least one of a repository URL, demo URL, or media attachment is required."]
    if errors:
        raise ValidationError(errors)

    # FR-SUB-003: "A `final` submission can still be edited by the team
    # until the submission deadline" -- finalizing is a readiness signal,
    # not a lock, so this is a no-op-safe flag flip, re-settable by any
    # further edit... except FR-SUB-001 has no un-finalize action, so
    # once set it simply stays true until the deadline locks everything.
    submission.is_finalized = True
    submission.save(update_fields=["is_finalized", "updated_at"])

    AuditLogEntry.objects.create(
        actor_id=actor.id, action="submission.finalized", target_type="submission", target_id=str(submission.id),
    )
    return submission


# ---- View a submission and its history --------------------------------------

def get_submission(*, actor, submission_id):
    submission = _get_submission_or_404(submission_id)
    _require_team_member_or_organizer(submission=submission, actor=actor)
    return submission


def get_submission_history(*, actor, submission_id):
    submission = _get_submission_or_404(submission_id)
    _require_team_member_or_organizer(submission=submission, actor=actor)
    versions = list(submission.versions.order_by("-created_at"))
    return submission, versions