"""
showcase -- services

All cross-model orchestration and business rules for FR-SHOWCASE-001/002
live here.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from apps.accounts.models import RoleAssignment
from apps.core.models import AuditLogEntry
from apps.hackathons.models import Hackathon
from apps.judging.models import JudgingRound, RoundResult
from apps.submissions.models import Submission
from apps.teams.models import TeamMember

from .models import ShowcaseOverride


class ConflictError(APIException):
    status_code = 409
    default_detail = "This action conflicts with the current showcase state."
    default_code = "conflict"


# ---- shared lookups / permission checks ------------------------------------

def _get_hackathon_or_404(hackathon_id):
    try:
        return Hackathon.objects.select_related("host_org").get(id=hackathon_id)
    except (Hackathon.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _get_submission_or_404(submission_id):
    try:
        return Submission.objects.select_related("hackathon", "team").get(id=submission_id)
    except (Submission.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _is_organizer(*, actor, hackathon):
    return RoleAssignment.objects.filter(
        user=actor,
        role="organizer",
        scope_type="organization",
        scope_id=hackathon.host_org_id,
    ).exists()


def _require_organizer(*, actor, hackathon):
    if not _is_organizer(actor=actor, hackathon=hackathon):
        raise PermissionDenied("Only the hackathon Organizer can perform this action.")


# ---- FR-SHOWCASE-001: publish / unpublish ----------------------------------

def publish_showcase(*, actor, hackathon_id):
    """POST /showcase/hackathons/{id}/publish -- FR-SHOWCASE-001.

    Precondition: "FR-JUDGE-003 has completed for all applicable rounds".
    Every judging round configured for the hackathon (the Overall round
    and any Challenge Track rounds) must be `closed` -- close_round()
    already materializes RoundResult as part of closing, so a closed
    round always has results.

    Idempotent: publishing an already-published showcase just re-confirms
    the existing showcase_published_at rather than erroring, since the
    Organizer action here is "make sure this is public", not "transition
    a state machine edge" -- re-running it (e.g. after adding a
    visibility override) should not require an unpublish/publish dance.
    """
    hackathon = _get_hackathon_or_404(hackathon_id)
    _require_organizer(actor=actor, hackathon=hackathon)

    if hackathon.status not in ("published", "archived"):
        raise ValidationError(
            "Only a published or archived hackathon's results can be showcased."
        )

    rounds = list(JudgingRound.objects.filter(hackathon=hackathon))
    if not rounds:
        raise ValidationError("This hackathon has no judging rounds configured yet.")
    if any(round.status != "closed" for round in rounds):
        raise ValidationError(
            "All judging rounds must be closed before publishing the showcase."
        )

    if hackathon.showcase_published_at:
        return hackathon

    with transaction.atomic():
        hackathon.showcase_published_at = timezone.now()
        hackathon.save(update_fields=["showcase_published_at", "updated_at"])
        AuditLogEntry.objects.create(
            actor_id=actor.id,
            action="showcase.published",
            target_type="hackathon",
            target_id=str(hackathon.id),
        )

    # FR-JUDGE-004 / FR-NOTIFY-001/002: "judging results published" --
    # the idempotency guard above (early return when already published)
    # means this only fires on the actual publish transition, not on a
    # re-confirming call.
    from apps.notifications.services import notify_judging_results_published

    notify_judging_results_published(hackathon)

    return hackathon

def unpublish_showcase(*, actor, hackathon_id):
    """POST /showcase/hackathons/{id}/unpublish -- FR-SHOWCASE-001/002.

    Reverses publish_showcase; per FR-SHOWCASE-002's acceptance
    criterion, every project from this hackathon is "removed
    automatically" from the cross-hackathon gallery the moment this
    happens, since list_gallery() below filters strictly on
    `showcase_published_at`, not a separate per-project flag.
    """
    hackathon = _get_hackathon_or_404(hackathon_id)
    _require_organizer(actor=actor, hackathon=hackathon)

    if not hackathon.showcase_published_at:
        raise ValidationError("This hackathon's showcase is not currently published.")

    with transaction.atomic():
        hackathon.showcase_published_at = None
        hackathon.save(update_fields=["showcase_published_at", "updated_at"])
        AuditLogEntry.objects.create(
            actor_id=actor.id,
            action="showcase.unpublished",
            target_type="hackathon",
            target_id=str(hackathon.id),
        )
    return hackathon


# ---- FR-SHOWCASE-001: per-submission visibility override -------------------

def set_submission_visibility(*, actor, submission_id, is_visible, reason):
    """PUT /showcase/submissions/{id}/visibility -- FR-SHOWCASE-001's
    "the Organizer may override visibility per submission with a logged
    reason" acceptance criterion. Works whether or not the showcase is
    already published, so an Organizer can pre-clear an exception before
    hitting publish.
    """
    submission = _get_submission_or_404(submission_id)
    _require_organizer(actor=actor, hackathon=submission.hackathon)

    reason = (reason or "").strip()
    if len(reason) < 10:
        raise ValidationError({"reason": "A visibility override reason must be at least 10 characters."})

    with transaction.atomic():
        override, created = ShowcaseOverride.objects.update_or_create(
            submission=submission,
            defaults={
                "hackathon": submission.hackathon,
                "is_visible": is_visible,
                "reason": reason,
                "created_by": actor,
            },
        )
        AuditLogEntry.objects.create(
            actor_id=actor.id,
            action="showcase.visibility_overridden",
            target_type="submission",
            target_id=str(submission.id),
            metadata={"isVisible": is_visible, "reason": reason},
        )
    return override


def clear_submission_visibility_override(*, actor, submission_id):
    """DELETE /showcase/submissions/{id}/visibility -- reverts a submission
    to the default eligibility-derived visibility (BR-006/BR-007)."""
    submission = _get_submission_or_404(submission_id)
    _require_organizer(actor=actor, hackathon=submission.hackathon)

    deleted, _ = ShowcaseOverride.objects.filter(submission=submission).delete()
    if not deleted:
        raise NotFound()
    AuditLogEntry.objects.create(
        actor_id=actor.id,
        action="showcase.visibility_override_cleared",
        target_type="submission",
        target_id=str(submission.id),
    )


def _is_submission_showcase_visible(submission, *, overrides_by_submission_id):
    """BR-006/BR-007: disqualified submissions are hidden by default,
    eligible ones are shown by default; an Organizer override always
    wins (FR-SHOWCASE-001)."""
    override = overrides_by_submission_id.get(submission.id)
    if override is not None:
        return override.is_visible
    return submission.eligibility_status == "eligible"


# ---- FR-SHOWCASE-001: single hackathon's public showcase page --------------

def _team_members_for(submission):
    """Members shown alongside a showcased project, linking out to their
    public profiles (FR-PROFILE-002) -- only accepted membership rows,
    and never the pending-invitation rows TeamMember also stores."""
    return list(
        TeamMember.objects.filter(team_id=submission.team_id, join_status="accepted")
        .select_related("user")
        .order_by("invited_at")
    )


def _result_rows(*, round, overrides_by_submission_id):
    """Rank-ordered, visibility-filtered rows for one judging round,
    carrying the placement (rank) and aggregate score FR-SHOWCASE-001
    requires -- never the raw per-judge scores BR-008 forbids exposing,
    since RoundResult only ever stores the materialized aggregate."""
    rows = []
    results = (
        RoundResult.objects.filter(round=round)
        .select_related("submission", "submission__team")
        .order_by("rank")
    )
    for result in results:
        submission = result.submission
        if not _is_submission_showcase_visible(
            submission, overrides_by_submission_id=overrides_by_submission_id,
        ):
            continue
        rows.append({
            "submission": submission,
            "team_members": _team_members_for(submission),
            "rank": result.rank,
            "aggregate_score": result.aggregate_score,
        })
    return rows


def get_hackathon_showcase(*, hackathon_id):
    """GET /showcase/hackathons/{id} -- FR-SHOWCASE-001. Public; raises
    NotFound (rather than a 403) if the Organizer hasn't published yet,
    so an unpublished hackathon's showcase page is indistinguishable from
    one that doesn't exist -- same "don't leak existence" reasoning as
    hackathons.get_hackathon hiding an unpublished draft."""
    hackathon = _get_hackathon_or_404(hackathon_id)
    if not hackathon.showcase_published_at:
        raise NotFound()

    overrides_by_submission_id = {
        override.submission_id: override
        for override in ShowcaseOverride.objects.filter(hackathon=hackathon)
    }

    rounds = list(
        JudgingRound.objects.filter(hackathon=hackathon)
        .select_related("track")
        .order_by("track_id")
    )
    overall_round = next((round for round in rounds if round.track_id is None), None)
    track_rounds = [round for round in rounds if round.track_id is not None]

    overall_results = (
        _result_rows(round=overall_round, overrides_by_submission_id=overrides_by_submission_id)
        if overall_round else []
    )
    track_results = [
        {
            "track": round.track,
            "results": _result_rows(round=round, overrides_by_submission_id=overrides_by_submission_id),
        }
        for round in track_rounds
    ]

    return {
        "hackathon": hackathon,
        "overall_results": overall_results,
        "track_results": track_results,
    }


# ---- FR-SHOWCASE-002: cross-hackathon public gallery -----------------------

def list_gallery(*, hackathon_id=None, institution_org_id=None, tag=None, limit=20, offset=0):
    """GET /showcase/gallery -- FR-SHOWCASE-002. A project appears here
    only once its parent hackathon's showcase is published, and
    disappears the moment the Organizer revokes that publication or
    hides it via a visibility override -- there is no separate
    "published to gallery" flag to fall out of sync with those two.

    This intentionally queries Submission across every hackathon at
    once, not through `Submission.objects.scoped_to(...)`
    (apps.core.managers.TenantScopedManager's single-tenant listing
    entry point, Design Spec Sec 3.3). That guard exists to stop an
    accidental cross-tenant data leak; a cross-hackathon public gallery
    of already-published, already-public showcase data is the one
    listing this app is *supposed* to do across tenants, and every row
    returned is independently re-checked for publish + visibility below,
    so nothing tenant-private leaks through this path.
    """
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    queryset = Submission.objects.filter(hackathon__showcase_published_at__isnull=False)

    if hackathon_id:
        queryset = queryset.filter(hackathon_id=hackathon_id)
    if institution_org_id:
        queryset = queryset.filter(hackathon__host_org_id=institution_org_id)
    if tag:
        queryset = queryset.filter(technologies__contains=[tag])

    visible_disqualified_ids = ShowcaseOverride.objects.filter(is_visible=True).values_list(
        "submission_id", flat=True,
    )
    hidden_ids = ShowcaseOverride.objects.filter(is_visible=False).values_list(
        "submission_id", flat=True,
    )
    queryset = queryset.filter(
        Q(eligibility_status="eligible") | Q(id__in=visible_disqualified_ids)
    ).exclude(id__in=hidden_ids)

    queryset = queryset.select_related("hackathon", "team").order_by(
        "-hackathon__showcase_published_at", "id",
    )

    total = queryset.count()
    results = list(queryset[offset:offset + limit])
    rows = [
        {"submission": submission, "team_members": _team_members_for(submission)}
        for submission in results
    ]
    return rows, total