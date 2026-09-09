"""
registrations -- services

Per Design Spec Sec 3.1: all business logic and cross-model orchestration
lives here.
"""

import uuid
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from apps.accounts.models import RoleAssignment
from apps.core.models import AuditLogEntry
from apps.hackathons.models import Hackathon
from apps.notifications.services import notify_registration_confirmed
from apps.organizations.models import Organization

from .models import Registration


class ConflictError(APIException):
    """HTTP 409 -- FR-REG-001: registering twice for the same hackathon."""
    status_code = 409
    default_detail = "You are already registered for this hackathon."
    default_code = "conflict"


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


def _get_registration_or_404(*, actor, hackathon_id):
    hackathon = _get_hackathon_or_404(hackathon_id)
    try:
        return Registration.objects.select_related("hackathon").get(
            hackathon=hackathon, user=actor,
        )
    except (Registration.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _email_domain(email):
    return email.strip().lower().rsplit("@", 1)[-1]


def _calculate_age(date_of_birth, *, as_of):
    return as_of.year - date_of_birth.year - (
        (as_of.month, as_of.day) < (date_of_birth.month, date_of_birth.day)
    )


def _check_eligibility(*, hackathon, actor, custom_answers=None):
    """FR-HACK-003 / FR-REG-001: reject with a specific, named-rule error
    rather than a generic rejection.

    `institution_restriction` matches on email domain against the
    restricted orgs' `primary_email_domain` -- the same mechanism
    organizations/services.py._attempt_domain_fast_track already uses to
    link an account to an organization. An org in the restriction list
    with no declared primary_email_domain can never be matched this way;
    that's a data-entry gap for the Organizer to fix, not something this
    function can work around.

    `age_restriction` (`{"min_age": int|null, "max_age": int|null}`) and
    `geographic_restriction` (`{"allowed_countries": ["ET", ...]}`) are
    checked against Account.date_of_birth/country -- both self-reported
    via FR-PROFILE-001, same trust level as `university`. A restricted
    hackathon blocks registration outright (with a distinct error) if the
    actor hasn't filled in the relevant profile field yet, rather than
    silently treating "unknown" as "eligible".
    """
    rules = hackathon.eligibility_rules or {}

    institution_restriction = rules.get("institution_restriction")
    if institution_restriction:
        allowed_domains = set(
            Organization.objects.filter(id__in=institution_restriction)
            .exclude(primary_email_domain__isnull=True)
            .exclude(primary_email_domain="")
            .values_list("primary_email_domain", flat=True)
        )
        if _email_domain(actor.email) not in allowed_domains:
            raise ValidationError({
                "eligibility": {
                    "rule": "institution_restriction",
                    "message": "Your institution is not on the allowed list for this hackathon.",
                }
            })

    age_restriction = rules.get("age_restriction") or {}
    min_age = age_restriction.get("min_age")
    max_age = age_restriction.get("max_age")
    if min_age is not None or max_age is not None:
        if not actor.date_of_birth:
            raise ValidationError({
                "eligibility": {
                    "rule": "age_restriction",
                    "message": "This hackathon has an age restriction. Add your date of birth to "
                               "your profile to register.",
                }
            })
        age = _calculate_age(actor.date_of_birth, as_of=timezone.now().date())
        if (min_age is not None and age < min_age) or (max_age is not None and age > max_age):
            raise ValidationError({
                "eligibility": {
                    "rule": "age_restriction",
                    "message": "You do not meet this hackathon's age requirement.",
                }
            })

    geographic_restriction = rules.get("geographic_restriction") or {}
    allowed_countries = geographic_restriction.get("allowed_countries")
    if allowed_countries:
        if not actor.country:
            raise ValidationError({
                "eligibility": {
                    "rule": "geographic_restriction",
                    "message": "This hackathon is restricted by country. Add your country to your "
                               "profile to register.",
                }
            })
        if actor.country.strip().upper() not in {c.strip().upper() for c in allowed_countries}:
            raise ValidationError({
                "eligibility": {
                    "rule": "geographic_restriction",
                    "message": "This hackathon is not open to participants in your country.",
                }
            })

    # Check open_to eligibility
    open_to = getattr(hackathon, "open_to", None) or ["ALL"]
    if "ALL" not in open_to and len(open_to) > 0:
        is_eligible = False
        allowed_labels = []

        custom_answers = custom_answers or {}
        personal_info = custom_answers.get("personalInfo") or {}
        role = (personal_info.get("role") or "").strip().lower()
        org_or_uni = (personal_info.get("organization") or personal_info.get("university") or getattr(actor, "university", "") or "").strip().lower()

        if "UNIVERSITY_STUDENT" in open_to:
            allowed_labels.append("University Students")
            is_student = (
                "student" in role or "university" in org_or_uni or "college" in org_or_uni or "institute" in org_or_uni
                or bool(getattr(actor, "university", None))
            )
            if is_student:
                is_eligible = True

        if "GOVERNMENT_PUBLIC_SECTOR" in open_to:
            allowed_labels.append("Government & Public Sector")
            is_gov = (
                "gov" in role or "public" in role or "ministry" in org_or_uni or "agency" in org_or_uni
                or "government" in org_or_uni
            )
            if is_gov:
                is_eligible = True

        if not is_eligible:
            groups_str = " and ".join(allowed_labels) if len(allowed_labels) <= 1 else " / ".join(allowed_labels)
            raise ValidationError({
                "eligibility": {
                    "rule": "open_to",
                    "message": f"This hackathon is currently open to {groups_str} only.",
                }
            })


# ---- FR-REG-001: register for a hackathon ----------------------------------

def register_for_hackathon(
    *, actor, hackathon_id, eligibility_confirmed=False, custom_answers=None,
    registration_type="solo", team_name=None, team_description="",
):
    hackathon = _get_hackathon_or_404(hackathon_id)

    # FR-REG-001 precondition: hackathon is published.
    if hackathon.status != "published":
        raise ValidationError("Registration is not open for this hackathon.")

    # BR-002: registration closes automatically at the deadline, server
    # time is authoritative regardless of client-side clock state.
    now = timezone.now()
    if now < hackathon.registration_opens_at or now > hackathon.registration_closes_at:
        raise ValidationError("Registration is not currently open for this hackathon.")

    # FR-REG-001: "attempting to register twice returns HTTP 409".
    existing_reg = Registration.objects.filter(hackathon=hackathon, user=actor).first()
    if existing_reg:
        if existing_reg.withdrawn_at is None:
            raise ConflictError()
        # Re-activating a withdrawn registration
        _check_eligibility(hackathon=hackathon, actor=actor, custom_answers=custom_answers)
        if registration_type not in ("solo", "looking_for_team", "create_team"):
            registration_type = "solo"
        with transaction.atomic():
            existing_reg.withdrawn_at = None
            existing_reg.eligibility_confirmed = eligibility_confirmed
            existing_reg.custom_answers = custom_answers
            existing_reg.registration_type = registration_type
            existing_reg.save()
            AuditLogEntry.objects.create(
                actor_id=actor.id, action="registration.created",
                target_type="registration", target_id=str(existing_reg.id),
            )
            if registration_type == "create_team" and team_name:
                from apps.teams.services import create_team
                create_team(
                    actor=actor,
                    hackathon_id=hackathon.id,
                    team_name=team_name,
                    description=team_description or "",
                )
        notify_registration_confirmed(existing_reg)
        return existing_reg

    _check_eligibility(hackathon=hackathon, actor=actor, custom_answers=custom_answers)

    if registration_type not in ("solo", "looking_for_team", "create_team"):
        registration_type = "solo"

    with transaction.atomic():
        registration = Registration.objects.create(
            hackathon=hackathon,
            user=actor,
            eligibility_confirmed=eligibility_confirmed,
            custom_answers=custom_answers,
            registration_type=registration_type,
        )
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="registration.created",
            target_type="registration", target_id=str(registration.id),
        )

        if registration_type == "create_team" and team_name:
            from apps.teams.services import create_team
            create_team(
                actor=actor,
                hackathon_id=hackathon.id,
                team_name=team_name,
                description=team_description or "",
            )

    # FR-REG-001: confirmation notification sent on success (FR-NOTIFY-001).
    # Cannot be opted out of -- see notifications.services.CRITICAL_CATEGORIES.
    notify_registration_confirmed(registration)

    return registration


def update_registration_type(*, actor, hackathon_id, registration_type):
    registration = _get_registration_or_404(actor=actor, hackathon_id=hackathon_id)
    if registration.withdrawn_at is not None:
        raise ValidationError("This registration has been withdrawn.")

    if registration_type not in ("solo", "looking_for_team", "create_team"):
        raise ValidationError("Invalid registration type.")

    registration.registration_type = registration_type
    registration.save(update_fields=["registration_type"])
    return registration


# ---- FR-REG-002: withdraw registration --------------------------------------

def withdraw_registration(*, actor, hackathon_id):
    registration = _get_registration_or_404(actor=actor, hackathon_id=hackathon_id)

    if registration.withdrawn_at is not None:
        raise ValidationError("This registration has already been withdrawn.")

    # BR-003: submissions/rosters lock at the submission deadline; a
    # withdrawal after that point is rejected, same reasoning as
    # FR-TEAM-004's leave/remove cutoff.
    if timezone.now() >= registration.hackathon.submission_closes_at:
        raise ValidationError("Cannot withdraw after the submission deadline.")

    # FR-REG-002 / FR-TEAM-004: leaving any team roster is a
    # teams-app concern, not a registrations-app one -- deliberately a
    # local import (not module-level) to avoid a hard import-time
    # coupling between the two apps. Done inside the same transaction as
    # the withdrawal itself so the two can't end up out of sync (e.g. a
    # withdrawn registration whose team roster cleanup silently failed).
    from apps.teams.services import remove_member_from_all_teams

    with transaction.atomic():
        registration.withdrawn_at = timezone.now()
        registration.save(update_fields=["withdrawn_at"])
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="registration.withdrawn",
            target_type="registration", target_id=str(registration.id),
        )
        remove_member_from_all_teams(hackathon=registration.hackathon, user=actor)

    return registration


# ---- FR-REG-003: view my registrations --------------------------------------

def list_my_registrations(*, actor):
    return (
        Registration.objects.filter(user=actor)
        .select_related("hackathon")
        .order_by("-registered_at")
    )


# ---- Organizer Registrations Query ------------------------------------------

def list_organizer_registrations(*, actor, hackathon_id=None, status=None, keyword=None, limit=50, offset=0):
    """Retrieves participant registrations for hackathons managed by the authenticated organizer.
    Strictly verifies server-side ownership. An organizer can only see registrations
    belonging to hackathons they created or manage for their host organizations.
    """
    if not actor or not actor.is_authenticated:
        raise PermissionDenied("Authentication required.")

    is_platform_admin = bool(getattr(actor, "is_platform_admin", False))

    if is_platform_admin:
        managed_hackathons = Hackathon.objects.all()
    else:
        user_org_ids = RoleAssignment.objects.filter(
            user=actor, role="organizer", scope_type="organization"
        ).values_list("scope_id", flat=True)
        created_org_ids = Organization.objects.filter(created_by=actor).values_list("id", flat=True)
        managed_hackathons = Hackathon.objects.filter(
            Q(host_org_id__in=user_org_ids) | Q(host_org_id__in=created_org_ids) | Q(created_by=actor)
        )

    managed_hackathon_ids = set(managed_hackathons.values_list("id", flat=True))

    # If a specific hackathon is requested, verify the organizer manages it
    if hackathon_id and str(hackathon_id).strip().lower() not in ("all", "null", "undefined", ""):
        try:
            target_id = uuid.UUID(str(hackathon_id).strip())
        except (ValueError, TypeError):
            raise NotFound("Invalid hackathon ID.")

        if target_id not in managed_hackathon_ids:
            raise PermissionDenied("You do not have permission to access registrations for this hackathon.")

        qs = Registration.objects.filter(hackathon_id=target_id)
        stats_qs = Registration.objects.filter(hackathon_id=target_id)
    else:
        if not managed_hackathon_ids:
            return [], 0, {
                "totalRegistrations": 0,
                "registeredCount": 0,
                "withdrawnCount": 0,
                "uniqueParticipants": 0,
                "managedHackathonsCount": 0,
            }
        qs = Registration.objects.filter(hackathon_id__in=managed_hackathon_ids)
        stats_qs = Registration.objects.filter(hackathon_id__in=managed_hackathon_ids)

    # Compute summary stats from real data
    total_reg = stats_qs.count()
    withdrawn_reg = stats_qs.filter(withdrawn_at__isnull=False).count()
    registered_reg = total_reg - withdrawn_reg
    unique_participants = stats_qs.values("user_id").distinct().count()

    stats = {
        "totalRegistrations": total_reg,
        "registeredCount": registered_reg,
        "withdrawnCount": withdrawn_reg,
        "uniqueParticipants": unique_participants,
        "managedHackathonsCount": len(managed_hackathon_ids),
    }

    # Status filter
    if status and str(status).strip().lower() not in ("all", "null", "undefined", ""):
        s_val = str(status).strip().lower()
        if s_val in ("withdrawn", "rejected"):
            qs = qs.filter(withdrawn_at__isnull=False)
        elif s_val in ("registered", "approved", "active"):
            qs = qs.filter(withdrawn_at__isnull=True)
        elif s_val == "pending":
            qs = qs.filter(withdrawn_at__isnull=True, verification_status__in=["pending", "unverified"])

    # Keyword search across participant name, email, university, organization, city, role, hackathon
    if keyword and str(keyword).strip():
        k = str(keyword).strip()
        qs = qs.filter(
            Q(user__full_name__icontains=k)
            | Q(user__email__icontains=k)
            | Q(user__university__icontains=k)
            | Q(user__organization__icontains=k)
            | Q(user__city__icontains=k)
            | Q(user__profession__icontains=k)
            | Q(hackathon__title__icontains=k)
        )

    qs = qs.select_related("hackathon", "user").order_by("-registered_at")
    total = qs.count()

    limit_val = max(1, min(int(limit), 100))
    offset_val = max(0, int(offset))
    results = list(qs[offset_val:offset_val + limit_val])

    return results, total, stats