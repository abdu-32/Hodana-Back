"""
platform_admin -- services

Per Design Spec Sec 3.1: all business logic and cross-model orchestration
lives here. This is the layer that enforces the business rules from
Document 02 Sec 4 and is unit-tested directly (NFR-MAINT-001: 80% coverage
target) without spinning up HTTP requests.

Implements FR-ADMIN-001 (moderation: suspend/reactivate a hackathon,
organization, or user account; the pending-organization-verification
dashboard) and FR-ADMIN-002 (platform-wide search).

FR-ADMIN-001's actual approve/reject action for organization verification
is NOT re-implemented here: apps.organizations.services already owns
review_organization_verification (it re-checks is_platform_admin itself,
same defense-in-depth pattern documented there), and
organizations.OrganizationVerificationReviewView already exposes it under
`IsPlatformAdmin`. Duplicating it here would just be two code paths for
one action. This module's `list_pending_organizations` below only wraps
the *read* side of that dashboard, which organizations.services exposes
as a query helper (`get_pending_verification_queue`) but never mounted
behind a view of its own.

Every permission check in this module is defense-in-depth: views.py
already restricts each endpoint to `IsPlatformAdmin`, but per this
codebase's established convention (organizations.services does the same
for `review_organization_verification`), services.py re-checks rather
than trusting the view layer alone.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import Account
from apps.core.models import AuditLogEntry
from apps.hackathons.models import Hackathon
from apps.organizations.models import Organization
from apps.organizations.services import get_pending_verification_queue

SEARCH_RESULT_LIMIT = 20  # FR-ADMIN-002 acceptance criterion: sub-2-second response at MVP scale


def _require_platform_admin(admin):
    """FR-ADMIN-001/002 precondition: "the requester holds the global
    Platform Admin role." Every public function in this module calls this
    first, so a non-admin always gets PermissionDenied (-> HTTP 403) no
    matter which entry point they hit."""
    if not (admin and getattr(admin, "is_authenticated", False) and getattr(admin, "is_platform_admin", False)):
        raise PermissionDenied()


def _require_reason(reason):
    """FR-ADMIN-001 acceptance criterion: "every moderation action records
    actor, target, timestamp, and a required reason." Applies uniformly to
    every suspend/reactivate action below -- unlike
    organizations.review_organization_verification, where the reason is
    only required on rejection, a moderation action here has no "obviously
    fine" branch that would justify skipping it."""
    if not reason or not reason.strip():
        raise ValidationError({"reason": "A reason is required for this action."})


def _get_hackathon_or_404(hackathon_id):
    try:
        return Hackathon.objects.get(id=hackathon_id)
    except (Hackathon.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _get_organization_or_404(organization_id):
    try:
        return Organization.objects.get(id=organization_id)
    except (Organization.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _get_account_or_404(user_id):
    try:
        return Account.objects.get(id=user_id)
    except (Account.DoesNotExist, ValueError, DjangoValidationError):
        raise NotFound()


def _record_moderation_action(*, admin, action, target_type, target_id, reason):
    """Single seam for the audit-log write every moderation action needs
    -- FR-ADMIN-001: "retained indefinitely for audit purposes." Never
    updated or deleted, per core.AuditLogEntry / Design Spec Sec 6.6."""
    AuditLogEntry.objects.create(
        actor_id=admin.id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        metadata={"reason": reason},
    )


# ---- FR-ADMIN-001: organization verification dashboard (read side) --------

def list_pending_organizations(*, admin):
    """GET /admin/organizations/pending. The query itself stays owned by
    apps.organizations (get_pending_verification_queue) -- see this
    module's docstring."""
    _require_platform_admin(admin)
    return get_pending_verification_queue()


# ---- FR-ADMIN-001: suspend / reactivate a hackathon ------------------------

def suspend_hackathon(*, admin, hackathon_id, reason):
    """Sets Hackathon.is_suspended, which apps.hackathons.services
    (list_hackathons / get_hackathon) then excludes from public discovery
    -- "immediately removes it from public discovery... while preserving
    all underlying data" (FR-ADMIN-001)."""
    _require_platform_admin(admin)
    _require_reason(reason)
    hackathon = _get_hackathon_or_404(hackathon_id)

    if hackathon.is_suspended:
        raise ValidationError("This hackathon is already suspended.")

    with transaction.atomic():
        hackathon.is_suspended = True
        hackathon.save(update_fields=["is_suspended", "updated_at"])
        _record_moderation_action(
            admin=admin, action="hackathon.suspended",
            target_type="hackathon", target_id=hackathon.id, reason=reason,
        )
    return hackathon


def reactivate_hackathon(*, admin, hackathon_id, reason):
    """Not called for directly by any FR-ADMIN-001 acceptance criterion,
    but suspension with no reverse action would be a one-way door for
    what the SRS frames as a moderation decision, not a permanent ban;
    kept symmetric with accounts/organizations below and logged the same
    way as any other moderation action."""
    _require_platform_admin(admin)
    _require_reason(reason)
    hackathon = _get_hackathon_or_404(hackathon_id)

    if not hackathon.is_suspended:
        raise ValidationError("This hackathon is not suspended.")

    with transaction.atomic():
        hackathon.is_suspended = False
        hackathon.save(update_fields=["is_suspended", "updated_at"])
        _record_moderation_action(
            admin=admin, action="hackathon.reactivated",
            target_type="hackathon", target_id=hackathon.id, reason=reason,
        )
    return hackathon


# ---- FR-ADMIN-001: suspend / reactivate an organization --------------------

def suspend_organization(*, admin, organization_id, reason):
    """Also removes every hackathon hosted by this organization from
    public discovery (apps.hackathons.services filters on
    host_org__is_suspended) -- a suspended organization's events shouldn't
    stay publicly listed just because the individual Hackathon row itself
    was never flagged."""
    _require_platform_admin(admin)
    _require_reason(reason)
    organization = _get_organization_or_404(organization_id)

    if organization.is_suspended:
        raise ValidationError("This organization is already suspended.")

    with transaction.atomic():
        organization.is_suspended = True
        organization.save(update_fields=["is_suspended", "updated_at"])
        _record_moderation_action(
            admin=admin, action="organization.suspended",
            target_type="organization", target_id=organization.id, reason=reason,
        )
    return organization


def reactivate_organization(*, admin, organization_id, reason):
    _require_platform_admin(admin)
    _require_reason(reason)
    organization = _get_organization_or_404(organization_id)

    if not organization.is_suspended:
        raise ValidationError("This organization is not suspended.")

    with transaction.atomic():
        organization.is_suspended = False
        organization.save(update_fields=["is_suspended", "updated_at"])
        _record_moderation_action(
            admin=admin, action="organization.reactivated",
            target_type="organization", target_id=organization.id, reason=reason,
        )
    return organization


# ---- FR-ADMIN-001: suspend / reactivate a user account ---------------------

def suspend_account(*, admin, user_id, reason):
    """Mirrors the account-suspension path Design Spec Sec 4.3 already
    describes for token_version: "admin-initiated suspension... increment
    token_version" so every existing access/refresh token for this
    account is rejected on its next use (NFR-SEC-005), on top of
    Account.is_active already going False via is_suspended."""
    _require_platform_admin(admin)
    _require_reason(reason)
    account = _get_account_or_404(user_id)

    if account.id == admin.id:
        raise ValidationError("A Platform Admin cannot suspend their own account.")
    if account.is_suspended:
        raise ValidationError("This account is already suspended.")

    with transaction.atomic():
        account.is_suspended = True
        account.token_version += 1  # NFR-SEC-005: revoke all existing sessions immediately
        account.save(update_fields=["is_suspended", "token_version", "updated_at"])
        _record_moderation_action(
            admin=admin, action="account.suspended",
            target_type="account", target_id=account.id, reason=reason,
        )
    return account


def reactivate_account(*, admin, user_id, reason):
    _require_platform_admin(admin)
    _require_reason(reason)
    account = _get_account_or_404(user_id)

    if not account.is_suspended:
        raise ValidationError("This account is not suspended.")

    with transaction.atomic():
        account.is_suspended = False
        account.save(update_fields=["is_suspended", "updated_at"])
        _record_moderation_action(
            admin=admin, action="account.reactivated",
            target_type="account", target_id=account.id, reason=reason,
        )
    return account


# ---- FR-ADMIN-002: platform-wide search ------------------------------------

def platform_search(*, admin, query):
    """GET /admin/search?q=... -- FR-ADMIN-002: "search across users,
    organizations, and hackathons by name or email." Every call is logged
    with the requesting admin's identity, per that FR's acceptance
    criterion, "given the sensitivity of cross-account search" (Design
    Spec Sec 6.6) -- this is the one search feature in the whole system
    that gets logged like a moderation action rather than just measured
    for latency."""
    _require_platform_admin(admin)

    query = (query or "").strip()
    if not query:
        raise ValidationError({"q": "A search query is required."})

    users = list(
        Account.objects.filter(Q(full_name__icontains=query) | Q(email__icontains=query))
        .order_by("full_name")[:SEARCH_RESULT_LIMIT]
    )
    organizations = list(
        Organization.objects.filter(name__icontains=query)
        .order_by("name")[:SEARCH_RESULT_LIMIT]
    )
    hackathons = list(
        Hackathon.objects.filter(title__icontains=query)
        .order_by("title")[:SEARCH_RESULT_LIMIT]
    )

    AuditLogEntry.objects.create(
        actor_id=admin.id,
        action="platform_admin.search",
        target_type="platform_search",
        target_id=str(admin.id),
        metadata={"query": query},
    )

    return {"users": users, "organizations": organizations, "hackathons": hackathons}
