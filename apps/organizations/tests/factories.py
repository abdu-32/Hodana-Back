"""
factory-boy factories for apps.organizations models.

Reuses apps.accounts.tests.factories.AccountFactory for created_by/
uploaded_by/reviewed_by rather than re-deriving account-creation logic
here -- Organization's FK to accounts.Account makes this a real
cross-app dependency (same as services.py importing
apps.accounts.models.RoleAssignment directly), not the kind of
same-shape duplication accounts/services.py's `_send_mail` comment
warns against.
"""

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import AccountFactory

from ..models import OrgVerificationDocument, OrgVerificationReview, Organization


class OrganizationFactory(DjangoModelFactory):
    """Defaults to `unverified` with no declared domain -- the shape most
    tests want as a starting point before exercising FR-ORG-002/003."""

    class Meta:
        model = Organization

    name = factory.Sequence(lambda n: f"Test Organization {n}")
    type = "university"
    contact_email = factory.Sequence(lambda n: f"contact{n}@example.com")
    primary_email_domain = None
    verification_status = "unverified"
    created_by = factory.SubFactory(AccountFactory)


class PendingOrganizationFactory(OrganizationFactory):
    """FR-ORG-003: already through submit_verification_documents, sitting
    in the admin review queue."""

    verification_status = "pending"


class VerifiedOrganizationFactory(OrganizationFactory):
    """Already verified -- e.g. for tests asserting the badge shows up,
    or that a verified org can't resubmit documents."""

    verification_status = "verified"
    verified_at = factory.LazyFunction(timezone.now)


class OrgVerificationDocumentFactory(DjangoModelFactory):
    class Meta:
        model = OrgVerificationDocument

    organization = factory.SubFactory(OrganizationFactory)
    file_url = factory.Sequence(lambda n: f"https://storage.example.com/verification-doc-{n}.pdf")
    uploaded_by = factory.SubFactory(AccountFactory)


class OrgVerificationReviewFactory(DjangoModelFactory):
    class Meta:
        model = OrgVerificationReview

    organization = factory.SubFactory(OrganizationFactory)
    reviewed_by = factory.SubFactory(AccountFactory, is_platform_admin=True)
    decision = "approved"
    rejection_reason = ""