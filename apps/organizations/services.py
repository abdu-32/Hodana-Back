"""
organizations -- services

Per Design Spec Sec 3.1: all business logic and cross-model orchestration
lives here. This is the layer that enforces the business rules from
Document 02 Sec 4 and is unit-tested directly (NFR-MAINT-001: 80% coverage
target) without spinning up HTTP requests.
"""

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import RoleAssignment
from apps.core.models import AuditLogEntry

from .models import Organization, OrgVerificationDocument, OrgVerificationReview

MAX_VERIFICATION_DOCUMENTS = 3  # FR-ORG-003 acceptance criterion

# FR-ORG-002: "a maintained list of recognized Ethiopian institutional
# domains." No such list is specified anywhere in Doc 02/05, so it is NOT
# hardcoded here -- that would mean silently guessing at real institutions.
# Populate settings.RECOGNIZED_INSTITUTIONAL_DOMAINS (e.g. config/settings/
# base.py) with the real list; auto-verification is a no-op until you do.
def _recognized_domains():
    return {d.lower() for d in getattr(settings, "RECOGNIZED_INSTITUTIONAL_DOMAINS", [])}


def _send_mail(*, subject, message, to):
    """Single seam to swap for a Celery task later. Synchronous for now.
    (Same pattern as accounts/services.py's helper -- duplicated rather than
    shared, per this codebase's existing convention of one per app.)"""
    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[to],
        fail_silently=False,
    )


def _email_domain(email):
    return email.strip().lower().rsplit("@", 1)[-1]


def _is_organizer_of(*, actor, organization):
    return RoleAssignment.objects.filter(
        user=actor, role="organizer", scope_type="organization", scope_id=organization.id,
    ).exists()


def _get_organization_or_404(organization_id):
    try:
        return Organization.objects.get(id=organization_id)
    except (Organization.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


# ---- FR-ORG-001: register an organization ----------------------------------

def get_organization(*, organization_id):
    """Public accessor for the view layer (e.g. GET /organizations/{id})
    -- _get_organization_or_404 stays private since every other caller of
    it is internal to this module."""
    return _get_organization_or_404(organization_id)

def register_organization(*, actor, name, type, contact_email, primary_email_domain=None):
    """Preconditions: actor is authenticated and verified (FR-AUTH-003)."""
    if actor.verification_status != "verified":
        raise PermissionDenied("Verify your email before registering an organization.")

    with transaction.atomic():
        organization = Organization.objects.create(
            name=name,
            type=type,
            contact_email=contact_email,
            primary_email_domain=(primary_email_domain or "").strip().lower() or None,
            created_by=actor,
        )
        RoleAssignment.objects.create(
            user=actor, role="organizer", scope_type="organization", scope_id=organization.id,
        )
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="organization.registered",
            target_type="organization", target_id=str(organization.id),
        )

    _attempt_domain_verification(organization=organization, actor=actor)
    return organization


# ---- FR-ORG-002: domain-based verification ---------------------------------

def _attempt_domain_verification(*, organization, actor):
    """Same-request auto-verify. No-op (leaves `unverified`) if there's no
    declared domain, it doesn't match the actor's email domain, or it isn't
    on the recognized-institution list -- falls through to FR-ORG-003."""
    if not organization.primary_email_domain:
        return organization

    if _email_domain(actor.email) != organization.primary_email_domain:
        return organization

    if organization.primary_email_domain not in _recognized_domains():
        return organization

    organization.verification_status = "verified"
    organization.verified_at = timezone.now()
    organization.save(update_fields=["verification_status", "verified_at", "updated_at"])
    AuditLogEntry.objects.create(
        actor_id=actor.id, action="organization.domain_verified",
        target_type="organization", target_id=str(organization.id),
    )
    return organization


# ---- FR-ORG-003: manual verification review --------------------------------

def submit_verification_documents(*, actor, organization_id, file_urls):
    organization = _get_organization_or_404(organization_id)

    if not _is_organizer_of(actor=actor, organization=organization):
        raise PermissionDenied("Only an Organizer of this organization can submit verification documents.")

    if organization.verification_status == "verified":
        raise ValidationError("This organization is already verified.")

    existing_count = organization.verification_documents.count()
    if existing_count + len(file_urls) > MAX_VERIFICATION_DOCUMENTS:
        raise ValidationError(
            f"An organization may have at most {MAX_VERIFICATION_DOCUMENTS} verification documents "
            f"({existing_count} already uploaded)."
        )

    with transaction.atomic():
        documents = [
            OrgVerificationDocument.objects.create(
                organization=organization, file_url=url, uploaded_by=actor,
            )
            for url in file_urls
        ]
        if organization.verification_status == "unverified":
            organization.verification_status = "pending"
            organization.save(update_fields=["verification_status", "updated_at"])
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="organization.verification_documents_submitted",
            target_type="organization", target_id=str(organization.id),
            metadata={"document_count": len(documents)},
        )

    return documents


def get_pending_verification_queue():
    """FR-ADMIN-001's review dashboard reads from this, not the model directly,
    so the query shape stays owned by this app."""
    return Organization.objects.filter(verification_status="pending").order_by("created_at")


def review_organization_verification(*, admin, organization_id, decision, rejection_reason=None):
    if not getattr(admin, "is_platform_admin", False):
        raise PermissionDenied()  # FR-ORG-003: reviewer must be a Platform Admin

    organization = _get_organization_or_404(organization_id)

    if organization.verification_status != "pending":
        raise ValidationError("This organization is not awaiting verification review.")

    if decision not in ("approved", "rejected"):
        raise ValidationError({"decision": "Must be 'approved' or 'rejected'."})

    if decision == "rejected" and not rejection_reason:
        raise ValidationError({"rejection_reason": "Required when rejecting an organization."})

    with transaction.atomic():
        review = OrgVerificationReview.objects.create(
            organization=organization,
            reviewed_by=admin,
            decision=decision,
            rejection_reason=rejection_reason if decision == "rejected" else "",
        )
        organization.verification_status = "verified" if decision == "approved" else "unverified"
        organization.verified_at = timezone.now() if decision == "approved" else None
        organization.save(update_fields=["verification_status", "verified_at", "updated_at"])
        AuditLogEntry.objects.create(
            actor_id=admin.id, action="organization.verification_reviewed",
            target_type="organization", target_id=str(organization.id),
            metadata={"decision": decision},
        )

    # FR-ORG-003: Organizer notified within 5 minutes of the admin decision.
    if decision == "approved":
        subject, body = "Your organization has been verified", (
            f"{organization.name} has been verified on Innovation Hub. "
            "You can now publish hackathons under this organization."
        )
    else:
        subject, body = "Your organization verification was not approved", (
            f"{organization.name}'s verification was not approved.\n\nReason: {rejection_reason}"
        )
    _send_mail(subject=subject, message=body, to=organization.contact_email)

    return review