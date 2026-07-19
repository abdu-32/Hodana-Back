"""
hackathons -- services

Per Design Spec Sec 3.1: all business logic and cross-model orchestration
lives here. This is the layer that enforces the business rules from
Document 02 Sec 4 and is unit-tested directly (NFR-MAINT-001: 80% coverage
target) without spinning up HTTP requests.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.db.utils import IntegrityError
from django.utils import timezone
from django.utils.text import slugify
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import RoleAssignment
from apps.core.models import AuditLogEntry
from apps.organizations.models import Organization

from .models import ChallengeTrack, Hackathon

# FR-DISC-001: registration-closed and completed events stay listed
# ("Registration Closed" / "Completed" status tags); only `draft` is ever
# hidden from the public catalog.
PUBLIC_STATUSES = ("published", "archived")

SIMPLE_UPDATE_FIELDS = (
    "title", "description", "banner_url", "rules", "prize_info", "eligibility_rules", "tags",
)
DATE_FIELDS = (
    "registration_opens_at", "registration_closes_at", "submission_opens_at", "submission_closes_at",
)


def _is_organizer_of_org(*, actor, org_id):
    return RoleAssignment.objects.filter(
        user=actor, role="organizer", scope_type="organization", scope_id=org_id,
    ).exists()


def _get_hackathon_or_404(hackathon_id):
    try:
        return Hackathon.objects.select_related("host_org").get(id=hackathon_id)
    except (Hackathon.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _get_organization_or_404(org_id):
    try:
        return Organization.objects.get(id=org_id)
    except (Organization.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _unique_slug(title, *, exclude_id=None):
    base = slugify(title)[:240] or "hackathon"
    slug = base
    suffix = 1
    qs = Hackathon.objects.all()
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    while qs.filter(slug=slug).exists():
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug


def _validate_pair(*, opens_at, closes_at, opens_field, closes_field):
    if closes_at <= opens_at:
        raise ValidationError({closes_field: f"Must be after {opens_field}."})


# ---- FR-HACK-001: create a hackathon ---------------------------------------

def create_hackathon(*, actor, host_org_id, title, registration_opens_at, registration_closes_at,
                      submission_opens_at, submission_closes_at, description="", slug=None,
                      banner_url="", rules="", prize_info="", location_mode="online",
                      eligibility_rules=None, tags=None):
    """FR-HACK-001. Creates a `draft` hackathon.

    Only the openapi HackathonCreateRequest's required set is enforced
    here; the rest of FR-HACK-001's "required fields" narrative
    (eligibility rules, rubric) is FR-HACK-005's publish gate (see
    _require_publish_ready below) -- matching "created in draft status...
    not publicly visible until FR-HACK-005": a draft is allowed to be
    incomplete by definition.
    """
    organization = _get_organization_or_404(host_org_id)

    # FR-HACK-001 precondition: "Organizer belonging to a verified organization".
    if not _is_organizer_of_org(actor=actor, org_id=organization.id):
        raise PermissionDenied("Only an Organizer of this organization can create a hackathon.")
    if organization.verification_status != "verified":
        raise PermissionDenied("The host organization must be verified before creating a hackathon.")

    _validate_pair(
        opens_at=registration_opens_at, closes_at=registration_closes_at,
        opens_field="registrationOpensAt", closes_field="registrationClosesAt",
    )
    _validate_pair(
        opens_at=submission_opens_at, closes_at=submission_closes_at,
        opens_field="submissionOpensAt", closes_field="submissionClosesAt",
    )
    # FR-HACK-001: "registration deadline must be on or after the current time".
    if registration_closes_at < timezone.now():
        raise ValidationError({"registrationClosesAt": "Must be in the future."})
    # FR-HACK-001: "submission deadline must be on or after the registration deadline".
    if submission_closes_at < registration_closes_at:
        raise ValidationError({"submissionClosesAt": "Must be on or after the registration deadline."})

    resolved_slug = (slug or "").strip().lower() or _unique_slug(title)
    if Hackathon.objects.filter(slug=resolved_slug).exists():
        raise ValidationError({"slug": "This slug is already in use."})

    with transaction.atomic():
        hackathon = Hackathon.objects.create(
            host_org=organization, title=title, slug=resolved_slug, description=description,
            banner_url=banner_url, registration_opens_at=registration_opens_at,
            registration_closes_at=registration_closes_at, submission_opens_at=submission_opens_at,
            submission_closes_at=submission_closes_at, rules=rules, prize_info=prize_info,
            location_mode=location_mode, eligibility_rules=eligibility_rules, tags=tags or [],
            status="draft", created_by=actor,
        )
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="hackathon.created",
            target_type="hackathon", target_id=str(hackathon.id),
        )
    return hackathon


# ---- FR-DISC-001/002/003 ----------------------------------------------------

def get_hackathon(*, hackathon_id, requester=None):
    """GET /hackathons/{id} -- FR-DISC-003. `draft` hackathons are hidden
    from everyone except an Organizer of the host org (FR-HACK-005: "not
    publicly visible until published"); Doc 04 doesn't mark this operation
    `security: []` the way it does the list endpoint, but the FR is
    unambiguous this must also work unauthenticated for published
    hackathons -- same "FR over stale contract" call as
    organizations.UserPublicProfileView."""
    hackathon = _get_hackathon_or_404(hackathon_id)
    if hackathon.status == "draft":
        is_owner_organizer = bool(
            requester and requester.is_authenticated
            and _is_organizer_of_org(actor=requester, org_id=hackathon.host_org_id)
        )
        if not is_owner_organizer:
            raise NotFound()
    return hackathon


def list_hackathons(*, keyword=None, tag=None, mode=None, status=None, limit=20, offset=0):
    """GET /hackathons -- FR-DISC-001/002. Always public: `draft`
    hackathons are never returned here regardless of the `status` filter,
    since this endpoint is unauthenticated (Doc 04: `security: []`)."""
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    queryset = Hackathon.objects.filter(status__in=PUBLIC_STATUSES)

    if status:
        if status not in PUBLIC_STATUSES:
            # e.g. `draft` -- never leak, and not a client error either;
            # just an empty result, like any other filter with no matches.
            return [], 0
        queryset = queryset.filter(status=status)

    if mode:
        queryset = queryset.filter(location_mode=mode)

    if tag:
        queryset = queryset.filter(tags__contains=[tag])

    if keyword:
        queryset = queryset.filter(Q(title__icontains=keyword) | Q(description__icontains=keyword))

    queryset = queryset.order_by("registration_closes_at")  # FR-DISC-001 default ordering
    total = queryset.count()
    results = list(queryset[offset:offset + limit])
    return results, total


# ---- FR-HACK-002/003/005: update + status transitions ----------------------

def update_hackathon(*, actor, hackathon_id, data):
    """PUT /hackathons/{id} -- FR-HACK-002 (timeline), FR-HACK-003
    (eligibility), and FR-HACK-005 (publish/unpublish/archive via
    `status`). Doc 04 has no dedicated /publish endpoint, so all of these
    share one entry point, matching how HackathonUpdateRequest bundles
    `status` alongside the other editable fields.

    Rubric editing (FR-HACK-004) is NOT handled here: DB Design Sec 4.7
    puts judging_criterion under apps.judging (keyed off judging_round,
    not Hackathon directly), and that app is still an unimplemented stub.
    """
    hackathon = _get_hackathon_or_404(hackathon_id)
    data = dict(data)

    if not _is_organizer_of_org(actor=actor, org_id=hackathon.host_org_id):
        raise PermissionDenied("Only an Organizer of the host organization can update this hackathon.")

    new_status = data.pop("status", None)

    # FR-HACK-002 precondition: "not yet archived" -- except the no-op
    # re-set of the same status, which isn't really an edit.
    if hackathon.status == "archived" and (data or new_status not in (None, "archived")):
        raise ValidationError("An archived hackathon cannot be edited.")

    if any(f in data for f in DATE_FIELDS):
        # Resolve the effective timeline (existing values overridden by
        # any provided ones) so ordering re-validation always sees a
        # complete, consistent set -- a partial update can't be allowed
        # to silently produce an internally-inconsistent timeline.
        effective = {f: data.get(f, getattr(hackathon, f)) for f in DATE_FIELDS}
        _validate_pair(
            opens_at=effective["registration_opens_at"], closes_at=effective["registration_closes_at"],
            opens_field="registrationOpensAt", closes_field="registrationClosesAt",
        )
        _validate_pair(
            opens_at=effective["submission_opens_at"], closes_at=effective["submission_closes_at"],
            opens_field="submissionOpensAt", closes_field="submissionClosesAt",
        )
        if effective["submission_closes_at"] < effective["registration_closes_at"]:
            raise ValidationError({"submissionClosesAt": "Must be on or after the registration deadline."})

        # BR-002: once registration has closed, its close date can't be
        # edited to (another) time in the past -- an edit must move it
        # into the future to reopen registration, not just tweak it while
        # still closed.
        already_closed = hackathon.registration_closes_at < timezone.now()
        if already_closed and "registration_closes_at" in data and data["registration_closes_at"] <= timezone.now():
            raise ValidationError(
                {"registrationClosesAt": "Cannot set a past registration close date once registration has closed."}
            )

    notify_participants = hackathon.status == "published" and any(f in data for f in DATE_FIELDS)

    update_fields = []
    with transaction.atomic():
        for field in SIMPLE_UPDATE_FIELDS + DATE_FIELDS:
            if field in data:
                setattr(hackathon, field, data[field])
                update_fields.append(field)

        if new_status:
            _apply_status_transition(hackathon=hackathon, new_status=new_status)
            update_fields.append("status")

        if update_fields:
            hackathon.save(update_fields=update_fields + ["updated_at"])
            AuditLogEntry.objects.create(
                actor_id=actor.id, action="hackathon.updated",
                target_type="hackathon", target_id=str(hackathon.id),
                metadata={"fields": update_fields},
            )

    # FR-HACK-002: "Editing a date after the hackathon is published
    # triggers a notification to all registered participants
    # (FR-NOTIFY-001)." apps.notifications is still an unimplemented stub
    # (no Notification model/service to call) -- flagging as a known gap
    # rather than silently skipping it.
    if notify_participants:
        pass  # TODO: apps.notifications.services.notify_hackathon_timeline_changed(hackathon)

    return hackathon


def _apply_status_transition(*, hackathon, new_status):
    

    if new_status == "published":
        _require_publish_ready(hackathon)
        hackathon.status = "published"
        # FR-HACK-005: "indexing into the public discovery catalog within
        # 60 seconds" -- there's no separate search index in this
        # codebase (list_hackathons queries Hackathon directly), so a
        # published row is immediately visible to FR-DISC-001; no async
        # job needed.

    elif new_status == "draft":
        # FR-HACK-005: "can be unpublished only if it has zero registrations".
        if hackathon.status != "published":
            raise ValidationError({"status": "Only a published hackathon can be unpublished."})
        if _registration_count(hackathon) > 0:
            raise ValidationError({"status": "Cannot unpublish a hackathon that already has registrations."})
        hackathon.status = "draft"

    elif new_status == "archived":
        # FR-HACK-005: "otherwise it can only be archived after its end date".
        if hackathon.status != "published":
            raise ValidationError({"status": "Only a published hackathon can be archived."})
        # See models.py docstring re: "end date" mapping to submission_closes_at.
        if timezone.now() < hackathon.submission_closes_at:
            raise ValidationError({"status": "Cannot archive a hackathon before its end date."})
        hackathon.status = "archived"

    else:
        raise ValidationError({"status": f"Unknown status '{new_status}'."})


def _require_publish_ready(hackathon):
    missing = []
    if not hackathon.title:
        missing.append("title")
    if not hackathon.description:
        missing.append("description")
    if not all([hackathon.registration_opens_at, hackathon.registration_closes_at,
                hackathon.submission_opens_at, hackathon.submission_closes_at]):
        missing.append("timeline")
    if not hackathon.eligibility_rules:
        missing.append("eligibilityRules")
    # NOTE: FR-HACK-005 also requires "a complete rubric" before publish
    # (BR-004). Not checked here: apps.judging owns judging_round /
    # judging_criterion (DB Design Sec 4.7) and doesn't exist yet, so
    # there's nothing to check against. BR-004 is under-enforced until
    # that app lands -- revisit this function then.
    if hackathon.host_org.verification_status != "verified":
        # BR-010, re-checked here in case the org's verification was
        # revoked between creation and publish.
        missing.append("hostOrganizationVerification")
    if missing:
        raise ValidationError({"missingFields": missing})


def _registration_count(hackathon):
    from apps.registrations.models import Registration
    return Registration.objects.filter(hackathon=hackathon, withdrawn_at__isnull=True).count()


# ---- DELETE /hackathons/{id} ------------------------------------------------

def delete_hackathon(*, actor, hackathon_id):
    """DELETE /hackathons/{id}. Not tied to a specific FR acceptance
    criterion in Doc 02 (FR-HACK-005 only defines unpublish/archive as
    lifecycle end-states for a *published* hackathon); restricting hard
    delete to `draft` hackathons so a real event's data can never be
    destroyed outright, only archived -- consistent with FR-HACK-005's own
    "preserving all underlying data" language for suspension.
    """
    hackathon = _get_hackathon_or_404(hackathon_id)
    if not _is_organizer_of_org(actor=actor, org_id=hackathon.host_org_id):
        raise PermissionDenied("Only an Organizer of the host organization can delete this hackathon.")
    if hackathon.status != "draft":
        raise ValidationError("Only a draft hackathon can be deleted; archive it instead.")

    with transaction.atomic():
        hackathon_id_str = str(hackathon.id)
        hackathon.delete()
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="hackathon.deleted",
            target_type="hackathon", target_id=hackathon_id_str,
        )


# ---- FR-TRACK-001/002 -------------------------------------------------------

def list_challenge_tracks(*, hackathon_id):
    hackathon = _get_hackathon_or_404(hackathon_id)
    return ChallengeTrack.objects.filter(hackathon=hackathon).order_by("created_at")


def create_challenge_track(*, actor, hackathon_id, sponsor_org_id, name, description="", prize="",
                            rubric_reference=""):
    """FR-TRACK-001. Doc 02 says "allow the Organizer to create"; Doc 04's
    summary ("organizer/sponsor") is broader than the FR -- treating the FR
    as authoritative and restricting to the Organizer, same as this app's
    other FR-over-contract calls."""
    hackathon = _get_hackathon_or_404(hackathon_id)

    if not _is_organizer_of_org(actor=actor, org_id=hackathon.host_org_id):
        raise PermissionDenied("Only an Organizer of the host organization can create a challenge track.")

    # FR-TRACK-001 precondition: "draft or published status, before
    # judging opens". apps.judging doesn't exist yet, so the "before
    # judging opens" half can't be checked -- same gap as
    # _require_publish_ready's rubric note.
    if hackathon.status not in ("draft", "published"):
        raise ValidationError("Challenge tracks can only be created for a draft or published hackathon.")

    sponsor_org = _get_organization_or_404(sponsor_org_id)

    if ChallengeTrack.objects.filter(hackathon=hackathon, name=name).exists():
        raise ValidationError({"name": "A track with this name already exists for this hackathon."})

    try:
        with transaction.atomic():
            track = ChallengeTrack.objects.create(
                hackathon=hackathon, sponsor_org=sponsor_org, name=name, description=description,
                prize=prize, rubric_reference=rubric_reference,
            )
            AuditLogEntry.objects.create(
                actor_id=actor.id, action="challenge_track.created",
                target_type="challenge_track", target_id=str(track.id),
            )
    except IntegrityError:
        # Race with the exists() check above -- the DB constraint is the
        # real guarantee (Design Spec Sec 3.3's "structural enforcement
        # over convention"), the pre-check just gives a nicer error.
        raise ValidationError({"name": "A track with this name already exists for this hackathon."})

    return track



# ---- FR-ELIG-001/002: eligibility screening ---------------------------------
#
# Submission is apps.submissions' model, but per Design Spec Sec 3.2's
# module-to-app mapping ELIG business logic lives here in apps.hackathons.
# apps.submissions is a downstream dependency of apps.hackathons (via
# apps.registrations/apps.teams), so importing apps.submissions.models at
# module level here would create a hackathons<->submissions import cycle
# (apps.submissions.services already imports apps.hackathons.models at
# module level) -- every reference to it below is a local, deferred import
# instead, same pattern as _registration_count's apps.registrations import.

# FR-ELIG-001's disqualification reason: "at least 10 characters".
MIN_DISQUALIFICATION_REASON_LENGTH = 10

ELIGIBILITY_STATUS_CHOICES = ("pending", "eligible", "disqualified")


def _get_submission_or_404(submission_id):
    from apps.submissions.models import Submission

    try:
        return Submission.objects.select_related("hackathon", "hackathon__host_org").get(id=submission_id)
    except (Submission.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _is_submission_locked(submission):
    """FR-ELIG-001 precondition: the submission status is `locked`
    (FR-SUB-003). Checked live against the hackathon's submission
    deadline, same as apps.submissions.services._require_not_locked --
    the Celery-Beat-driven `locked_at` write (DB Design Sec 4.6) isn't
    the source of truth for this check since that job isn't implemented
    yet; `locked_at` is honored too in case a future job does set it."""
    return submission.locked_at is not None or timezone.now() >= submission.hackathon.submission_closes_at


def screen_submission(*, actor, submission_id, eligibility_status, reason=""):
    """PUT /submissions/{id}/eligibility -- FR-ELIG-001. Marks a locked
    submission `eligible` or `disqualified`. Note the model default is
    already `eligible` (BR-006: "screening is opt-out for compliant
    submissions"), so this is only ever called to disqualify a submission
    or to reinstate a previously-disqualified one.
    """
    submission = _get_submission_or_404(submission_id)
    hackathon = submission.hackathon

    if not _is_organizer_of_org(actor=actor, org_id=hackathon.host_org_id):
        raise PermissionDenied("Only an Organizer of the host organization can screen submissions.")

    if eligibility_status not in ("eligible", "disqualified"):
        raise ValidationError({"eligibilityStatus": "Must be 'eligible' or 'disqualified'."})

    # FR-ELIG-001 precondition.
    if not _is_submission_locked(submission):
        raise ValidationError(
            "Only a locked submission (past the submission deadline) can be screened."
        )

    reason = (reason or "").strip()
    if eligibility_status == "disqualified":
        # FR-ELIG-001: "Disqualification requires a reason of at least 10
        # characters, shown to the affected team."
        if len(reason) < MIN_DISQUALIFICATION_REASON_LENGTH:
            raise ValidationError({
                "reason": f"A disqualification reason of at least {MIN_DISQUALIFICATION_REASON_LENGTH} characters is required.",
            })
    else:
        # Reinstating to eligible clears any prior disqualification reason
        # -- an eligible submission carrying a stale disqualification
        # reason would be misleading to the team viewing it.
        reason = ""

    with transaction.atomic():
        submission.eligibility_status = eligibility_status
        submission.eligibility_reason = reason
        submission.eligibility_reviewed_by = actor
        submission.eligibility_reviewed_at = timezone.now()
        submission.save(update_fields=[
            "eligibility_status", "eligibility_reason", "eligibility_reviewed_by", "eligibility_reviewed_at",
        ])
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="submission.eligibility_screened",
            target_type="submission", target_id=str(submission.id),
            metadata={"eligibilityStatus": eligibility_status, "reason": reason},
        )

    return submission


def list_submissions_for_screening(*, actor, hackathon_id, eligibility_status=None, limit=20, offset=0):
    """GET /hackathons/{id}/submissions -- FR-ELIG-002 bulk screening
    view. Organizer-only listing of a hackathon's locked submissions
    (the pool FR-ELIG-001 actually operates on), optionally filtered by
    current screening status, so a full cohort can be screened
    efficiently via one-click screen_submission calls per row.

    Doc 04's listSubmissions operation on this path also accepts a
    `trackId` filter, shared with the general submissions-browsing use
    case. Not implemented here: apps.submissions has no SubmissionTrack
    model yet (FR-TRACK assignment -- assignSubmissionTrack /
    removeSubmissionTrack -- is unimplemented), so there is nothing to
    filter against. Flagging as a known gap rather than faking the filter.
    """
    from apps.submissions.models import Submission

    hackathon = _get_hackathon_or_404(hackathon_id)

    if not _is_organizer_of_org(actor=actor, org_id=hackathon.host_org_id):
        raise PermissionDenied("Only an Organizer of the host organization can view submissions for screening.")

    if eligibility_status and eligibility_status not in ELIGIBILITY_STATUS_CHOICES:
        raise ValidationError({"eligibilityStatus": f"Must be one of {', '.join(ELIGIBILITY_STATUS_CHOICES)}."})

    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    queryset = Submission.objects.filter(hackathon=hackathon)

    # FR-ELIG-002 scope: "listing all locked submissions" -- before the
    # submission deadline nothing in this hackathon is locked yet, so the
    # screening queue is legitimately empty rather than an error (same
    # "empty result over exception" call as list_hackathons' status
    # filter), letting an Organizer open this view early without a 404/400.
    if timezone.now() < hackathon.submission_closes_at:
        queryset = queryset.none()

    if eligibility_status:
        queryset = queryset.filter(eligibility_status=eligibility_status)

    queryset = queryset.order_by("-submitted_at")
    total = queryset.count()
    results = list(queryset[offset:offset + limit])
    return results, total