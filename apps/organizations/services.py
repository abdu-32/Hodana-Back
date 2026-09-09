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
from django.db.models import Q
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


import threading


def _send_mail(*, subject, message, to):
    """Sends email in a background daemon thread so network SMTP latency never blocks the HTTP response."""
    def _deliver():
        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[to],
                fail_silently=True,
            )
        except Exception:
            pass

    threading.Thread(target=_deliver, daemon=True).start()


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

def list_my_organizations(*, actor):
    """Returns organizations created by the actor or where actor is assigned an organizer role."""
    user_org_ids = RoleAssignment.objects.filter(
        user=actor, role="organizer", scope_type="organization"
    ).values_list("scope_id", flat=True)
    return (
        Organization.objects.filter(Q(created_by=actor) | Q(id__in=user_org_ids))
        .distinct()
        .prefetch_related("verification_reviews", "verification_documents")
        .order_by("-created_at")
    )


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
            verification_status="pending",
            created_by=actor,
        )
        RoleAssignment.objects.create(
            user=actor, role="organizer", scope_type="organization", scope_id=organization.id,
        )
        AuditLogEntry.objects.create(
            actor_id=actor.id, action="organization.registered",
            target_type="organization", target_id=str(organization.id),
        )

    _attempt_domain_fast_track(organization=organization, actor=actor)
    return organization


# ---- FR-ORG-002: domain-matched fast-track (revised) ------------------------

def _attempt_domain_fast_track(*, organization, actor):
    """Same-request fast-track into the FR-ORG-003 pending queue. No-op
    (leaves `unverified`) if there's no declared domain, it doesn't match
    the actor's email domain, or it isn't on the recognized-institution
    list -- in all those cases the org just sits `unverified` until the
    organizer submits documents per FR-ORG-003.

    IMPORTANT: this intentionally no longer sets `verified_status` straight
    to "verified". A domain match only proves the registrant *has an email
    address* at that domain -- e.g. any student at a university -- not that
    they're authorized to represent that institution as an organization on
    the platform. Treating "the org's declared domain happens to match my
    own inbox" as sufficient identity/authority proof was the original
    design; it let anyone with a university email auto-verify "the
    university" itself with zero human review. Instead, a domain match now
    only fast-tracks the organization straight into the pending-review
    queue (skipping straight past the "no signal at all" unverified state)
    with `domain_fast_tracked=True`, so a Platform Admin sees why it's
    there and can approve it quickly -- but a human still always makes the
    actual verification decision via review_organization_verification
    below, same as any other FR-ORG-003 submission."""
    if not organization.primary_email_domain:
        return organization

    if _email_domain(actor.email) != organization.primary_email_domain:
        return organization

    if organization.primary_email_domain not in _recognized_domains():
        return organization

    organization.verification_status = "pending"
    organization.domain_fast_tracked = True
    organization.save(update_fields=["verification_status", "domain_fast_tracked", "updated_at"])
    AuditLogEntry.objects.create(
        actor_id=actor.id, action="organization.domain_matched_fast_tracked",
        target_type="organization", target_id=str(organization.id),
        metadata={"domain": organization.primary_email_domain},
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
    so the query shape stays owned by this app. Domain-fast-tracked orgs sort
    first: they carry a stronger corroborating signal (a matching recognized
    institutional domain) than a cold FR-ORG-003 document submission, so an
    admin working the queue top-down clears the "easy" ones first."""
    return Organization.objects.filter(verification_status__in=["pending", "unverified"]).order_by(
        "-domain_fast_tracked", "created_at"
    )


def review_organization_verification(*, admin, organization_id, decision, rejection_reason=None):
    if not getattr(admin, "is_platform_admin", False):
        raise PermissionDenied()  # FR-ORG-003: reviewer must be a Platform Admin

    organization = _get_organization_or_404(organization_id)

    if organization.verification_status not in ("pending", "unverified"):
        raise ValidationError("This organization is not awaiting verification review.")

    decision_norm = str(decision or "").lower().strip()
    if decision_norm in ("approve", "verified"):
        decision_norm = "approved"
    elif decision_norm in ("reject",):
        decision_norm = "rejected"

    if decision_norm not in ("approved", "rejected"):
        raise ValidationError({"decision": "Must be 'approved' or 'rejected'."})

    if decision_norm == "rejected" and not rejection_reason:
        raise ValidationError({"rejection_reason": "Required when rejecting an organization."})

    with transaction.atomic():
        review = OrgVerificationReview.objects.create(
            organization=organization,
            reviewed_by=admin,
            decision=decision_norm,
            rejection_reason=rejection_reason if decision_norm == "rejected" else "",
        )
        organization.verification_status = "verified" if decision_norm == "approved" else "rejected"
        organization.verified_at = timezone.now() if decision_norm == "approved" else None
        organization.save(update_fields=["verification_status", "verified_at", "updated_at"])

        if decision_norm == "approved" and organization.created_by:
            RoleAssignment.objects.get_or_create(
                user=organization.created_by,
                role="organizer",
                scope_type="organization",
                scope_id=organization.id,
            )
            if not getattr(organization.created_by, "is_platform_admin", False):
                organization.created_by.role = "organizer"
            organization.created_by.verification_status = "verified"
            organization.created_by.save(update_fields=["role", "verification_status"])

        AuditLogEntry.objects.create(
            actor_id=admin.id, action="organization.verification_reviewed",
            target_type="organization", target_id=str(organization.id),
            metadata={"decision": decision_norm},
        )

    # Informational notification email -- contains NO activation links, tokens, or one-time URLs
    if decision_norm == "approved":
        subject = "Your Organizer Application Has Been Approved"
        body = (
            "Congratulations!\n\n"
            "Your application to become an organizer on Innovation Hub for Ethiopia has been approved by the platform administrator.\n\n"
            "You can now sign in to your existing account and access your Organizer Dashboard.\n\n"
            "Thank you,\n"
            "Innovation Hub for Ethiopia Platform Team"
        )
    else:
        subject = "Your organization verification was not approved"
        body = (
            f"{organization.name}'s verification was not approved.\n\nReason: {rejection_reason}"
        )

    recipient = organization.contact_email or (organization.created_by.email if organization.created_by else None)
    if recipient:
        _send_mail(subject=subject, message=body, to=recipient)

    return review