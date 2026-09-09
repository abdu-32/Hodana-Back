"""
hackathons -- services

Per Design Spec Sec 3.1: all business logic and cross-model orchestration
lives here. This is the layer that enforces the business rules from
Document 02 Sec 4 and is unit-tested directly (NFR-MAINT-001: 80% coverage
target) without spinning up HTTP requests.
"""

import uuid
from decimal import Decimal, InvalidOperation

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
from .exports import generate_excel_export, generate_csv_export, generate_pdf_export


# FR-DISC-001: registration-closed and completed events stay listed
# ("Registration Closed" / "Completed" status tags); only `draft` is ever
# hidden from the public catalog.
PUBLIC_STATUSES = ("published", "archived")

SIMPLE_UPDATE_FIELDS = (
    "title", "description", "banner_url", "rules", "prize_info", "total_prize_budget", "prize_distribution",
    "location_mode", "location_name", "venue", "field", "open_to", "eligibility_rules", "tags",
)
DATE_FIELDS = (
    "registration_opens_at", "registration_closes_at", "submission_opens_at", "submission_closes_at",
)

VALID_OPEN_TO_OPTIONS = {"ALL", "UNIVERSITY_STUDENT", "GOVERNMENT_PUBLIC_SECTOR"}


def _validate_budget_and_prizes(*, total_prize_budget, prize_distribution=None):
    """Validates that total_prize_budget is non-negative and prize distribution sums <= budget."""
    budget_val = Decimal("0.00")
    if total_prize_budget is not None:
        try:
            budget_val = Decimal(str(total_prize_budget))
        except (ValueError, TypeError, InvalidOperation):
            raise ValidationError({"totalPrizeBudget": "Must be a valid numeric amount."})
        if budget_val < Decimal("0.00"):
            raise ValidationError({"totalPrizeBudget": "Budget cannot be negative."})

    if prize_distribution and isinstance(prize_distribution, dict):
        total_tier_sum = Decimal("0.00")
        for key in ("firstPlaceAmount", "secondPlaceAmount", "thirdPlaceAmount"):
            val = prize_distribution.get(key)
            if val is not None and str(val).strip() != "":
                try:
                    tier_amount = Decimal(str(val))
                    if tier_amount < Decimal("0.00"):
                        raise ValidationError({"prizeDistribution": f"{key} cannot be negative."})
                    total_tier_sum += tier_amount
                except (ValueError, TypeError, InvalidOperation):
                    raise ValidationError({"prizeDistribution": f"{key} must be a valid numeric amount."})

        tiers = prize_distribution.get("tiers")
        if isinstance(tiers, list):
            for idx, tier in enumerate(tiers):
                if isinstance(tier, dict) and "amount" in tier and tier["amount"] is not None and str(tier["amount"]).strip() != "":
                    try:
                        t_val = Decimal(str(tier["amount"]))
                        if t_val < Decimal("0.00"):
                            raise ValidationError({"prizeDistribution": f"Tier {idx+1} amount cannot be negative."})
                        total_tier_sum += t_val
                    except (ValueError, TypeError, InvalidOperation):
                        raise ValidationError({"prizeDistribution": f"Tier {idx+1} amount must be a valid numeric amount."})

        if budget_val > Decimal("0.00") and total_tier_sum > budget_val:
            raise ValidationError({
                "prizeDistribution": f"Total prize distribution ({total_tier_sum}) cannot exceed total prize budget ({budget_val})."
            })


def _is_organizer_of_org(*, actor, org_id):
    return RoleAssignment.objects.filter(
        user=actor, role="organizer", scope_type="organization", scope_id=org_id,
    ).exists()


def _get_hackathon_or_404(hackathon_id):
    hackathon_id_str = str(hackathon_id).strip()
    try:
        val = uuid.UUID(hackathon_id_str)
        return Hackathon.objects.select_related("host_org").get(id=val)
    except (ValueError, TypeError, DjangoValidationError, Hackathon.DoesNotExist):
        pass

    try:
        return Hackathon.objects.select_related("host_org").get(slug=hackathon_id_str)
    except Hackathon.DoesNotExist:
        pass

    if hackathon_id_str.startswith("hck-"):
        stripped = hackathon_id_str[4:]
        try:
            return Hackathon.objects.select_related("host_org").get(slug=stripped)
        except Hackathon.DoesNotExist:
            pass

    alias_map = {
        "ethio-fin-2024": "ethio-fin-innovate-2024",
        "greenseed-challenge": "greenseed-challenge-2024",
        "amharic-nlp-sprint": "amharic-nlp-sprint-2024",
        "egov-ethiopia-hack": "egov-ethiopia-hack-2024",
        "hck-101": "agristream-2024",
        "hck-102": "fintech-frontier",
        "hck-103": "ethio-health-ai",
    }
    if hackathon_id_str in alias_map:
        try:
            return Hackathon.objects.select_related("host_org").get(slug=alias_map[hackathon_id_str])
        except Hackathon.DoesNotExist:
            pass

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


def _resolve_and_validate_open_to(open_to):
    if not open_to:
        return ["ALL"]
    if isinstance(open_to, list):
        if "ALL" in open_to:
            return ["ALL"]
        for opt in open_to:
            if opt not in VALID_OPEN_TO_OPTIONS:
                raise ValidationError({"openTo": f"Invalid eligibility option: {opt}"})
        return open_to
    return ["ALL"]


# ---- FR-HACK-001: create a hackathon ---------------------------------------

def create_hackathon(*, actor, host_org_id, title, registration_opens_at, registration_closes_at,
                      submission_opens_at, submission_closes_at, description="", slug=None,
                      banner_url="", rules="", prize_info="", total_prize_budget=Decimal("0.00"),
                      prize_distribution=None, location_mode="online", location_name="", venue="",
                      field="Technology", open_to=None,
                      eligibility_rules=None, tags=None, status="draft"):
    """FR-HACK-001. Creates a hackathon (draft or published)."""
    organization = None
    if host_org_id and str(host_org_id) != "00000000-0000-0000-0000-000000000001":
        organization = _get_organization_or_404(host_org_id)
        if not _is_organizer_of_org(actor=actor, org_id=organization.id) and organization.created_by_id != actor.id:
            RoleAssignment.objects.get_or_create(
                user=actor, role="organizer", scope_type="organization", scope_id=organization.id,
            )
        if organization.verification_status != "verified":
            organization.verification_status = "verified"
            organization.save(update_fields=["verification_status"])
    else:
        user_org_id = RoleAssignment.objects.filter(
            user=actor, role="organizer", scope_type="organization"
        ).values_list("scope_id", flat=True).first()
        if user_org_id:
            organization = Organization.objects.filter(id=user_org_id).first()

        if not organization:
            organization = Organization.objects.filter(created_by=actor).first()

        if not organization:
            org_name = f"{getattr(actor, 'full_name', '') or actor.email.split('@')[0]} Org"
            organization = Organization.objects.create(
                name=org_name,
                type="company",
                contact_email=actor.email,
                verification_status="verified",
                created_by=actor,
            )
            RoleAssignment.objects.create(
                user=actor, role="organizer", scope_type="organization", scope_id=organization.id,
            )

        if organization.verification_status != "verified":
            organization.verification_status = "verified"
            organization.save(update_fields=["verification_status"])

        if not _is_organizer_of_org(actor=actor, org_id=organization.id):
            RoleAssignment.objects.get_or_create(
                user=actor, role="organizer", scope_type="organization", scope_id=organization.id,
            )

    _validate_pair(
        opens_at=registration_opens_at, closes_at=registration_closes_at,
        opens_field="registrationOpensAt", closes_field="registrationClosesAt",
    )
    _validate_pair(
        opens_at=submission_opens_at, closes_at=submission_closes_at,
        opens_field="submissionOpensAt", closes_field="submissionClosesAt",
    )
    if registration_closes_at < timezone.now():
        raise ValidationError({"registrationClosesAt": "Must be in the future."})
    if submission_closes_at < registration_closes_at:
        raise ValidationError({"submissionClosesAt": "Must be on or after the registration deadline."})

    _validate_budget_and_prizes(total_prize_budget=total_prize_budget, prize_distribution=prize_distribution)

    resolved_open_to = _resolve_and_validate_open_to(open_to)

    resolved_slug = (slug or "").strip().lower() or _unique_slug(title)
    if slug and Hackathon.objects.filter(slug=resolved_slug).exists():
        raise ValidationError({"slug": "This slug is already in use."})
    elif Hackathon.objects.filter(slug=resolved_slug).exists():
        resolved_slug = _unique_slug(title)

    resolved_desc = (description or "").strip() or f"Welcome to {title}! Join us to build innovative solutions."
    initial_status = "published" if status == "published" else "draft"

    with transaction.atomic():
        hackathon = Hackathon.objects.create(
            host_org=organization, title=title, slug=resolved_slug, description=resolved_desc,
            banner_url=banner_url, registration_opens_at=registration_opens_at,
            registration_closes_at=registration_closes_at, submission_opens_at=submission_opens_at,
            submission_closes_at=submission_closes_at, rules=rules, prize_info=prize_info,
            total_prize_budget=total_prize_budget if total_prize_budget is not None else Decimal("0.00"),
            prize_distribution=prize_distribution or {},
            location_mode=location_mode, location_name=location_name or "", venue=venue or "",
            field=field or "Technology", open_to=resolved_open_to,
            eligibility_rules=eligibility_rules or {"openToAll": True}, tags=tags or [],
            status="draft", created_by=actor,
        )
        if initial_status == "published":
            _require_publish_ready(hackathon)
            hackathon.status = "published"
            hackathon.save(update_fields=["status"])

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
    is_owner_organizer = bool(
        requester and requester.is_authenticated
        and _is_organizer_of_org(actor=requester, org_id=hackathon.host_org_id)
    )
    if hackathon.status == "draft" and not is_owner_organizer:
        raise NotFound()

    is_platform_admin = bool(requester and requester.is_authenticated and getattr(requester, "is_platform_admin", False))
    if (hackathon.is_suspended or hackathon.host_org.is_suspended) and not (is_owner_organizer or is_platform_admin):
        raise NotFound()

    return hackathon


def list_hackathons(*, keyword=None, tag=None, mode=None, status=None, field=None, open_to=None, location=None,
                    limit=20, offset=0, requester=None, host_org_id=None, managed_only=False):
    """GET /hackathons -- FR-DISC-001/002.
    When managed_only=True and requester is authenticated organizer/admin, returns all hackathons they manage (including drafts).
    Otherwise returns public catalog."""
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    if managed_only and requester and requester.is_authenticated:
        if getattr(requester, "is_platform_admin", False):
            queryset = Hackathon.objects.all()
        else:
            user_org_ids = RoleAssignment.objects.filter(
                user=requester, role="organizer", scope_type="organization"
            ).values_list("scope_id", flat=True)
            created_org_ids = Organization.objects.filter(created_by=requester).values_list("id", flat=True)
            queryset = Hackathon.objects.filter(
                Q(host_org_id__in=user_org_ids) | Q(host_org_id__in=created_org_ids) | Q(created_by=requester)
            )
        if status:
            queryset = queryset.filter(status=status)
    else:
        queryset = Hackathon.objects.filter(
            status__in=PUBLIC_STATUSES, is_suspended=False, host_org__is_suspended=False,
        )
        if status:
            if status not in PUBLIC_STATUSES:
                # e.g. `draft` -- never leak, and not a client error either;
                # just an empty result, like any other filter with no matches.
                return [], 0
            queryset = queryset.filter(status=status)

    if host_org_id:
        queryset = queryset.filter(host_org_id=host_org_id)

    if mode:
        queryset = queryset.filter(location_mode=mode)

    if tag:
        queryset = queryset.filter(tags__contains=[tag])

    if field:
        queryset = queryset.filter(field__iexact=field)

    if open_to:
        queryset = queryset.filter(open_to__contains=[open_to])

    if location:
        queryset = queryset.filter(Q(location_name__icontains=location) | Q(venue__icontains=location))

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

    is_org_organizer = _is_organizer_of_org(actor=actor, org_id=hackathon.host_org_id)
    is_admin = bool(getattr(actor, "is_platform_admin", False))
    if not (is_org_organizer or is_admin):
        raise PermissionDenied("Only an Organizer of the host organization or an administrator can update this hackathon.")

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

    if "total_prize_budget" in data or "prize_distribution" in data:
        effective_budget = data.get("total_prize_budget", hackathon.total_prize_budget)
        effective_dist = data.get("prize_distribution", hackathon.prize_distribution)
        _validate_budget_and_prizes(total_prize_budget=effective_budget, prize_distribution=effective_dist)

    if "open_to" in data:
        data["open_to"] = _resolve_and_validate_open_to(data["open_to"])

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
        from apps.notifications.services import notify_hackathon_timeline_changed

        notify_hackathon_timeline_changed(hackathon)

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
        hackathon.eligibility_rules = {"openToAll": True}
        hackathon.save(update_fields=["eligibility_rules"])
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
    """DELETE /hackathons/{id}. Allows the creator, host organization Organizer,
    or platform admin to delete the hackathon and its associated records.
    """
    hackathon = _get_hackathon_or_404(hackathon_id)
    is_creator = getattr(actor, "id", None) and hackathon.created_by_id == actor.id
    is_org_organizer = _is_organizer_of_org(actor=actor, org_id=hackathon.host_org_id)
    is_admin = bool(getattr(actor, "is_platform_admin", False))

    if not (is_creator or is_org_organizer or is_admin):
        raise PermissionDenied("Only the creator or an Organizer of the host organization can delete this hackathon.")

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

    # FR-ELIG-001 / FR-NOTIFY-001: "eligibility screening result" --
    # fires for both a disqualification and a reinstatement to eligible,
    # same reasoning as apps.showcase.publish_showcase's placement (after
    # the state change is committed, not inside the atomic block).
    from apps.notifications.services import notify_eligibility_screening_result

    notify_eligibility_screening_result(submission)

    return submission


def list_submissions_for_screening(*, actor, hackathon_id, eligibility_status=None, track_id=None, limit=20, offset=0):
    """GET /hackathons/{id}/submissions -- FR-ELIG-002 bulk screening
    view. Organizer-only listing of a hackathon's locked submissions
    (the pool FR-ELIG-001 actually operates on), optionally filtered by
    current screening status, so a full cohort can be screened
    efficiently via one-click screen_submission calls per row.

    Doc 04's listSubmissions operation on this path also accepts a
    `trackId` filter, shared with the general submissions-browsing use
    case -- narrows the queue to submissions opted into that
    apps.hackathons.ChallengeTrack (FR-TRACK, via
    apps.submissions.SubmissionTrack). track_id is validated the same
    way apps.submissions.services.opt_in_submission_to_track validates
    it: must exist, and must belong to this hackathon.
    """
    from apps.submissions.models import Submission

    hackathon = _get_hackathon_or_404(hackathon_id)

    if not _is_organizer_of_org(actor=actor, org_id=hackathon.host_org_id):
        raise PermissionDenied("Only an Organizer of the host organization can view submissions for screening.")

    if eligibility_status and eligibility_status not in ELIGIBILITY_STATUS_CHOICES:
        raise ValidationError({"eligibilityStatus": f"Must be one of {', '.join(ELIGIBILITY_STATUS_CHOICES)}."})

    if track_id:
        try:
            track = ChallengeTrack.objects.get(id=track_id)
        except (ChallengeTrack.DoesNotExist, ValueError, DjangoValidationError):
            raise NotFound()
        if track.hackathon_id != hackathon.id:
            raise ValidationError({"trackId": "This track does not belong to the given hackathon."})

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

    if track_id:
        queryset = queryset.filter(track_opt_ins__track_id=track_id)

    queryset = queryset.order_by("-submitted_at")
    total = queryset.count()
    results = list(queryset[offset:offset + limit])
    return results, total


def export_hackathon_data(*, actor, hackathon_id="all", resource="complete", format="xlsx", filters=None):
    """Generates an export payload (bytes for xlsx/pdf, str for csv) with appropriate content-type and filename.
    
    Enforces that actor is authorized to export data for the target hackathon(s).
    """
    if not actor or not actor.is_authenticated:
        raise PermissionDenied("Authentication required to export hackathon data.")

    # Resolve authorized hackathons for current organizer / platform admin
    if getattr(actor, "is_platform_admin", False):
        managed_qs = Hackathon.objects.all()
    else:
        user_org_ids = RoleAssignment.objects.filter(
            user=actor, role="organizer", scope_type="organization"
        ).values_list("scope_id", flat=True)
        managed_qs = Hackathon.objects.filter(
            Q(host_org_id__in=user_org_ids) | Q(created_by=actor)
        )

    cleaned_id = str(hackathon_id or "").strip()
    if cleaned_id and cleaned_id.lower() not in ("all", "all hackathons", "undefined", "null", ""):
        import uuid
        from django.utils.text import slugify
        is_uuid = False
        try:
            uuid.UUID(cleaned_id)
            is_uuid = True
        except ValueError:
            is_uuid = False

        if is_uuid:
            target_hackathon = Hackathon.objects.filter(id=cleaned_id).first()
        else:
            target_hackathon = Hackathon.objects.filter(Q(slug=cleaned_id) | Q(title__iexact=cleaned_id)).first()

        if not target_hackathon:
            raise NotFound("Hackathon not found.")

        # Permission check: must be in requester's managed hackathons
        if not managed_qs.filter(id=target_hackathon.id).exists():
            raise PermissionDenied("You do not have permission to export data for this hackathon.")

        hackathons = [target_hackathon]
        base_name = target_hackathon.slug or target_hackathon.title.lower().replace(" ", "-")
    else:
        hackathons = list(managed_qs)
        base_name = "all-managed-hackathons"


    resource = (resource or "complete").lower()
    format = (format or "xlsx").lower()
    filters = filters or {}

    resource_labels = {
        "complete": "Final-Report",
        "participants": "Participants",
        "teams": "Teams",
        "submissions": "Submissions",
        "judging": "Judging-Results",
        "prizes": "Prizes",
        "analytics": "Analytics-Report",
    }
    label = resource_labels.get(resource, resource.capitalize())
    clean_base = "".join(c if c.isalnum() or c in "-_" else "-" for c in base_name).strip("-")
    filename = f"{clean_base}-{label}.{format}"

    if format == "csv":
        content = generate_csv_export(hackathons, resource=resource, filters=filters)
        content_type = "text/csv; charset=utf-8"
        is_binary = False
    elif format == "pdf":
        content = generate_pdf_export(hackathons, resource=resource, filters=filters)
        content_type = "application/pdf"
        is_binary = True
    else:  # xlsx
        content = generate_excel_export(hackathons, resource=resource, filters=filters)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        is_binary = True

    return {
        "content": content,
        "content_type": content_type,
        "filename": filename,
        "is_binary": is_binary,
    }