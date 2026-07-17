"""
Unit tests against organizations/services.py directly (Design Spec Sec 3.1),
per the 80% coverage target in NFR-MAINT-001. Prefer these over
HTTP-level tests for business-rule coverage.

Test IDs in each docstring/comment match Document 07 Sec 6's named cases
(TC-ORG-*) where one exists; additional cases beyond that representative
list are included for branch coverage of services.py.
"""

import uuid

import pytest
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.accounts.models import RoleAssignment
from apps.core.models import AuditLogEntry
from apps.organizations import services

from .factories import (
    OrgVerificationDocumentFactory,
    OrganizationFactory,
    PendingOrganizationFactory,
    VerifiedOrganizationFactory,
)

# ---------------------------------------------------------------------------
# get_organization
# ---------------------------------------------------------------------------


class TestGetOrganization:
    def test_returns_organization_by_id(self, organization):
        result = services.get_organization(organization_id=organization.id)
        assert result.id == organization.id

    def test_nonexistent_id_raises_not_found(self):
        with pytest.raises(NotFound):
            services.get_organization(organization_id=uuid.uuid4())

    def test_malformed_id_raises_not_found_not_a_500(self):
        with pytest.raises(NotFound):
            services.get_organization(organization_id="not-a-uuid")


# ---------------------------------------------------------------------------
# FR-ORG-001: register an organization
# ---------------------------------------------------------------------------


class TestRegisterOrganization:
    def test_creates_organization_owned_by_actor(self, verified_account):
        organization = services.register_organization(
            actor=verified_account,
            name="Addis Ababa University",
            type="university",
            contact_email="contact@aau.edu.et",
        )

        assert organization.name == "Addis Ababa University"
        assert organization.type == "university"
        assert organization.contact_email == "contact@aau.edu.et"
        assert organization.created_by_id == verified_account.id
        assert organization.verification_status == "unverified"

    def test_grants_actor_the_organizer_role_scoped_to_the_new_org(self, verified_account):
        organization = services.register_organization(
            actor=verified_account, name="Some Org", type="company", contact_email="c@example.com",
        )

        assert RoleAssignment.objects.filter(
            user=verified_account, role="organizer", scope_type="organization", scope_id=organization.id,
        ).exists()

    def test_writes_audit_log_entry(self, verified_account):
        organization = services.register_organization(
            actor=verified_account, name="Some Org", type="company", contact_email="c@example.com",
        )

        assert AuditLogEntry.objects.filter(
            action="organization.registered", target_id=str(organization.id),
        ).exists()

    def test_TC_ORG_001a_unverified_actor_cannot_register(self, unverified_account):
        with pytest.raises(PermissionDenied):
            services.register_organization(
                actor=unverified_account, name="Some Org", type="company", contact_email="c@example.com",
            )

    def test_primary_email_domain_is_normalized(self, verified_account):
        organization = services.register_organization(
            actor=verified_account,
            name="Some Org",
            type="company",
            contact_email="c@example.com",
            primary_email_domain="  Example.COM  ",
        )
        assert organization.primary_email_domain == "example.com"

    def test_blank_primary_email_domain_is_stored_as_none(self, verified_account):
        organization = services.register_organization(
            actor=verified_account, name="Some Org", type="company", contact_email="c@example.com",
            primary_email_domain="",
        )
        assert organization.primary_email_domain is None


# ---------------------------------------------------------------------------
# FR-ORG-002: domain-based auto-verification
# ---------------------------------------------------------------------------


class TestDomainAutoVerification:
    def test_TC_ORG_002a_matching_recognized_domain_auto_verifies(self, verified_account, settings):
        settings.RECOGNIZED_INSTITUTIONAL_DOMAINS = ["aau.edu.et"]
        verified_account.email = "student@aau.edu.et"
        verified_account.save(update_fields=["email"])

        organization = services.register_organization(
            actor=verified_account, name="AAU", type="university", contact_email="c@aau.edu.et",
            primary_email_domain="aau.edu.et",
        )

        assert organization.verification_status == "verified"
        assert organization.verified_at is not None
        assert AuditLogEntry.objects.filter(
            action="organization.domain_verified", target_id=str(organization.id),
        ).exists()

    def test_no_declared_domain_stays_unverified(self, verified_account, settings):
        settings.RECOGNIZED_INSTITUTIONAL_DOMAINS = ["aau.edu.et"]

        organization = services.register_organization(
            actor=verified_account, name="Some Org", type="company", contact_email="c@example.com",
        )
        assert organization.verification_status == "unverified"

    def test_domain_not_matching_actors_email_stays_unverified(self, verified_account, settings):
        settings.RECOGNIZED_INSTITUTIONAL_DOMAINS = ["aau.edu.et"]
        verified_account.email = "someone@other.com"
        verified_account.save(update_fields=["email"])

        organization = services.register_organization(
            actor=verified_account, name="AAU", type="university", contact_email="c@aau.edu.et",
            primary_email_domain="aau.edu.et",
        )
        assert organization.verification_status == "unverified"

    def test_matching_but_unrecognized_domain_stays_unverified(self, verified_account, settings):
        settings.RECOGNIZED_INSTITUTIONAL_DOMAINS = []  # nothing recognized
        verified_account.email = "student@aau.edu.et"
        verified_account.save(update_fields=["email"])

        organization = services.register_organization(
            actor=verified_account, name="AAU", type="university", contact_email="c@aau.edu.et",
            primary_email_domain="aau.edu.et",
        )
        assert organization.verification_status == "unverified"


# ---------------------------------------------------------------------------
# FR-ORG-003: manual verification review -- submitting documents
# ---------------------------------------------------------------------------


class TestSubmitVerificationDocuments:
    def test_organizer_can_submit_documents(self, verified_account, organization, organizer_role):
        documents = services.submit_verification_documents(
            actor=verified_account, organization_id=organization.id,
            file_urls=["https://storage.example.com/a.pdf"],
        )
        assert len(documents) == 1
        assert documents[0].organization_id == organization.id
        assert documents[0].uploaded_by_id == verified_account.id

    def test_non_organizer_is_forbidden(self, verified_account, organization):
        # no organizer_role fixture used -- verified_account has no
        # RoleAssignment for this org.
        with pytest.raises(PermissionDenied):
            services.submit_verification_documents(
                actor=verified_account, organization_id=organization.id,
                file_urls=["https://storage.example.com/a.pdf"],
            )

    def test_transitions_unverified_org_to_pending(self, verified_account, organization, organizer_role):
        services.submit_verification_documents(
            actor=verified_account, organization_id=organization.id,
            file_urls=["https://storage.example.com/a.pdf"],
        )
        organization.refresh_from_db()
        assert organization.verification_status == "pending"

    def test_writes_audit_log_entry_with_document_count(self, verified_account, organization, organizer_role):
        services.submit_verification_documents(
            actor=verified_account, organization_id=organization.id,
            file_urls=["https://storage.example.com/a.pdf", "https://storage.example.com/b.pdf"],
        )
        entry = AuditLogEntry.objects.get(
            action="organization.verification_documents_submitted", target_id=str(organization.id),
        )
        assert entry.metadata["document_count"] == 2

    def test_already_verified_org_rejects_submission(self, verified_account, verified_organization):
        RoleAssignment.objects.create(
            user=verified_account, role="organizer", scope_type="organization",
            scope_id=verified_organization.id,
        )
        with pytest.raises(ValidationError):
            services.submit_verification_documents(
                actor=verified_account, organization_id=verified_organization.id,
                file_urls=["https://storage.example.com/a.pdf"],
            )

    def test_TC_ORG_003a_exceeding_max_documents_is_rejected(self, verified_account, organization, organizer_role):
        for _ in range(services.MAX_VERIFICATION_DOCUMENTS):
            OrgVerificationDocumentFactory(organization=organization)

        with pytest.raises(ValidationError):
            services.submit_verification_documents(
                actor=verified_account, organization_id=organization.id,
                file_urls=["https://storage.example.com/one-too-many.pdf"],
            )

    def test_submission_exactly_at_the_limit_succeeds(self, verified_account, organization, organizer_role):
        file_urls = [
            f"https://storage.example.com/{i}.pdf" for i in range(services.MAX_VERIFICATION_DOCUMENTS)
        ]
        documents = services.submit_verification_documents(
            actor=verified_account, organization_id=organization.id, file_urls=file_urls,
        )
        assert len(documents) == services.MAX_VERIFICATION_DOCUMENTS

    def test_nonexistent_organization_raises_not_found(self, verified_account):
        with pytest.raises(NotFound):
            services.submit_verification_documents(
                actor=verified_account, organization_id=uuid.uuid4(),
                file_urls=["https://storage.example.com/a.pdf"],
            )


# ---------------------------------------------------------------------------
# FR-ADMIN-001: pending verification queue
# ---------------------------------------------------------------------------


class TestGetPendingVerificationQueue:
    def test_returns_only_pending_organizations(self):
        pending = PendingOrganizationFactory()
        OrganizationFactory(verification_status="unverified")
        VerifiedOrganizationFactory()

        queue = list(services.get_pending_verification_queue())

        assert queue == [pending]

    def test_orders_oldest_first(self):
        first = PendingOrganizationFactory()
        second = PendingOrganizationFactory()

        queue = list(services.get_pending_verification_queue())

        assert queue.index(first) < queue.index(second)


# ---------------------------------------------------------------------------
# FR-ORG-003: manual verification review -- admin decision
# ---------------------------------------------------------------------------


class TestReviewOrganizationVerification:
    def test_non_platform_admin_is_forbidden(self, verified_account, pending_organization):
        with pytest.raises(PermissionDenied):
            services.review_organization_verification(
                admin=verified_account, organization_id=pending_organization.id, decision="approved",
            )

    def test_TC_ORG_003b_approval_verifies_the_organization(self, platform_admin, pending_organization, mailoutbox):
        review = services.review_organization_verification(
            admin=platform_admin, organization_id=pending_organization.id, decision="approved",
        )

        pending_organization.refresh_from_db()
        assert pending_organization.verification_status == "verified"
        assert pending_organization.verified_at is not None
        assert review.decision == "approved"

    def test_approval_notifies_organizer_by_email(self, platform_admin, pending_organization, mailoutbox):
        services.review_organization_verification(
            admin=platform_admin, organization_id=pending_organization.id, decision="approved",
        )
        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [pending_organization.contact_email]
        assert "verified" in mailoutbox[0].subject.lower()

    def test_TC_ORG_003c_rejection_reverts_to_unverified(self, platform_admin, pending_organization, mailoutbox):
        review = services.review_organization_verification(
            admin=platform_admin, organization_id=pending_organization.id, decision="rejected",
            rejection_reason="Documents were illegible.",
        )

        pending_organization.refresh_from_db()
        assert pending_organization.verification_status == "unverified"
        assert pending_organization.verified_at is None
        assert review.decision == "rejected"
        assert review.rejection_reason == "Documents were illegible."

    def test_rejection_notifies_organizer_with_reason(self, platform_admin, pending_organization, mailoutbox):
        services.review_organization_verification(
            admin=platform_admin, organization_id=pending_organization.id, decision="rejected",
            rejection_reason="Documents were illegible.",
        )
        assert len(mailoutbox) == 1
        assert "Documents were illegible." in mailoutbox[0].body

    def test_rejection_without_reason_is_rejected(self, platform_admin, pending_organization):
        with pytest.raises(ValidationError):
            services.review_organization_verification(
                admin=platform_admin, organization_id=pending_organization.id, decision="rejected",
            )

    def test_invalid_decision_value_is_rejected(self, platform_admin, pending_organization):
        with pytest.raises(ValidationError):
            services.review_organization_verification(
                admin=platform_admin, organization_id=pending_organization.id, decision="maybe",
            )

    def test_organization_not_pending_is_rejected(self, platform_admin, organization):
        # `organization` fixture defaults to `unverified`, never submitted.
        with pytest.raises(ValidationError):
            services.review_organization_verification(
                admin=platform_admin, organization_id=organization.id, decision="approved",
            )

    def test_already_verified_organization_cannot_be_re_reviewed(self, platform_admin, verified_organization):
        with pytest.raises(ValidationError):
            services.review_organization_verification(
                admin=platform_admin, organization_id=verified_organization.id, decision="approved",
            )

    def test_nonexistent_organization_raises_not_found(self, platform_admin):
        with pytest.raises(NotFound):
            services.review_organization_verification(
                admin=platform_admin, organization_id=uuid.uuid4(), decision="approved",
            )