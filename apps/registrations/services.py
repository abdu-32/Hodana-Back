"""
registrations -- services

Per Design Spec Sec 3.1: all business logic and cross-model orchestration
lives here.
"""

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, ValidationError

from apps.core.models import AuditLogEntry
from apps.hackathons.models import Hackathon
from apps.organizations.models import Organization

from .models import Registration


class ConflictError(APIException):
    """HTTP 409 -- FR-REG-001: registering twice for the same hackathon."""
    status_code = 409
    default_detail = "You are already registered for this hackathon."
    default_code = "conflict"


def _send_mail(*, subject, message, to):
    """Single seam to swap for a Celery task later. Synchronous for now.
    apps.notifications is still an unimplemented stub -- same pattern as
    organizations/services.py and accounts/services.py."""
    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[to],
        fail_silently=False,
    )


def _get_hackathon_or_404(hackathon_id):
    try:
        return Hackathon.objects.select_related("host_org").get(id=hackathon_id)
    except (Hackathon.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _get_registration_or_404(*, actor, hackathon_id):
    try:
        return Registration.objects.select_related("hackathon").get(
            hackathon_id=hackathon_id, user=actor,
        )
    except (Registration.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _email_domain(email):
    return email.strip().lower().rsplit("@", 1)[-1]


def _check_eligibility(*, hackathon, actor):
    """FR-HACK-003 / FR-REG-001: reject with a specific, named-rule error
    rather than a generic rejection.

    Only `institution_restriction` is checkable against the current data
    model: Account has no FK to Organization, only a free-text
    `university` field, so this matches on email domain against the
    restricted orgs' `primary_email_domain` -- the same mechanism
    organizations/services.py._attempt_domain_verification already uses
    to link an account to an organization. An org in the restriction list
    with no declared primary_email_domain can never be matched this way;
    that's a data-entry gap for the Organizer to fix, not something this
    function can work around.

    `age_restriction` and `geographic_restriction` (also named in
    FR-HACK-003) are NOT enforced here: Account has no date_of_birth or
    country/location field anywhere in Doc 05. Silently treating them as
    "not present" would misrepresent enforcement as complete when it
    isn't -- flagging as a known gap rather than guessing at a data
    source that doesn't exist. Add the fields + this check together when
    that's prioritized.
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


# ---- FR-REG-001: register for a hackathon ----------------------------------

def register_for_hackathon(*, actor, hackathon_id, eligibility_confirmed=False, custom_answers=None):
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
    if Registration.objects.filter(hackathon=hackathon, user=actor).exists():
        raise ConflictError()

    _check_eligibility(hackathon=hackathon, actor=actor)

    with transaction.atomic():
        registration = Registration.objects.create(
            hackathon=hackathon,
            user=actor,
            eligibility_confirmed=eligibility_confirmed,
            custom_answers=custom_answers,
        )
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="registration.created",
            target_type="registration", target_id=str(registration.id),
        )

    # FR-REG-001: confirmation notification sent on success (FR-NOTIFY-001).
    _send_mail(
        subject=f"You're registered for {hackathon.title}",
        message=f"You have successfully registered for {hackathon.title}.",
        to=actor.contact_email or actor.email,
    )

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

    with transaction.atomic():
        registration.withdrawn_at = timezone.now()
        registration.save(update_fields=["withdrawn_at"])
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="registration.withdrawn",
            target_type="registration", target_id=str(registration.id),
        )

    # TODO: FR-REG-002 requires removing the participant from any team
    # roster they belonged to (FR-TEAM-004). apps.teams is still an
    # unimplemented stub with no Team model to reference -- wire this in
    # once that app exists, e.g.:
    #   apps.teams.services.remove_member_from_all_teams(hackathon=registration.hackathon, user=actor)

    return registration


# ---- FR-REG-003: view my registrations --------------------------------------

def list_my_registrations(*, actor):
    return (
        Registration.objects.filter(user=actor)
        .select_related("hackathon")
        .order_by("-registered_at")
    )