"""
Unit tests against platform_admin/services.py directly (Design Spec Sec 3.1),
per the 80% coverage target in NFR-MAINT-001. Prefer these over
HTTP-level tests for business-rule coverage.
"""

import uuid

import pytest
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.core.models import AuditLogEntry
from apps.hackathons.models import Hackathon
from apps.organizations.models import Organization

from .. import services

# ---------------------------------------------------------------------------
# Shared precondition: every function requires is_platform_admin
# ---------------------------------------------------------------------------


class TestPlatformAdminPrecondition:
    """FR-ADMIN-001/002: "The requester holds the global Platform Admin
    role" -- checked identically by every function in this module."""

    def test_list_pending_organizations_rejects_non_admin(self, regular_account):
        with pytest.raises(PermissionDenied):
            services.list_pending_organizations(admin=regular_account)

    def test_suspend_hackathon_rejects_non_admin(self, regular_account, hackathon):
        with pytest.raises(PermissionDenied):
            services.suspend_hackathon(admin=regular_account, hackathon_id=hackathon.id, reason="terms violation")

    def test_suspend_organization_rejects_non_admin(self, regular_account, organization):
        with pytest.raises(PermissionDenied):
            services.suspend_organization(admin=regular_account, organization_id=organization.id, reason="terms violation")

    def test_suspend_account_rejects_non_admin(self, regular_account, platform_admin):
        with pytest.raises(PermissionDenied):
            services.suspend_account(admin=regular_account, user_id=platform_admin.id, reason="terms violation")

    def test_platform_search_rejects_non_admin(self, regular_account):
        with pytest.raises(PermissionDenied):
            services.platform_search(admin=regular_account, query="anything")


# ---------------------------------------------------------------------------
# FR-ADMIN-001: pending organization verification dashboard
# ---------------------------------------------------------------------------


class TestListPendingOrganizations:
    def test_returns_only_pending_organizations(self, platform_admin, pending_organization, verified_organization, organization):
        results = list(services.list_pending_organizations(admin=platform_admin))
        assert results == [pending_organization]


# ---------------------------------------------------------------------------
# FR-ADMIN-001: suspend / reactivate a hackathon
# ---------------------------------------------------------------------------


class TestSuspendHackathon:
    def test_suspends_and_logs_reason(self, platform_admin, hackathon):
        result = services.suspend_hackathon(admin=platform_admin, hackathon_id=hackathon.id, reason="Fraudulent prize claims")

        assert result.is_suspended is True
        hackathon.refresh_from_db()
        assert hackathon.is_suspended is True

        entry = AuditLogEntry.objects.get(action="hackathon.suspended", target_id=str(hackathon.id))
        assert entry.actor_id == platform_admin.id
        assert entry.metadata["reason"] == "Fraudulent prize claims"

    def test_requires_a_reason(self, platform_admin, hackathon):
        with pytest.raises(ValidationError):
            services.suspend_hackathon(admin=platform_admin, hackathon_id=hackathon.id, reason="")

    def test_already_suspended_raises(self, platform_admin, suspended_hackathon):
        with pytest.raises(ValidationError):
            services.suspend_hackathon(admin=platform_admin, hackathon_id=suspended_hackathon.id, reason="again")

    def test_unknown_hackathon_raises_not_found(self, platform_admin):
        with pytest.raises(NotFound):
            services.suspend_hackathon(admin=platform_admin, hackathon_id=uuid.uuid4(), reason="x")

    def test_removed_from_public_discovery(self, platform_admin, published_hackathon):
        """FR-ADMIN-001 acceptance criterion: "Suspending a hackathon
        immediately removes it from public discovery... while preserving
        all underlying data." """
        from apps.hackathons.services import list_hackathons

        services.suspend_hackathon(admin=platform_admin, hackathon_id=published_hackathon.id, reason="Under investigation")

        results, total = list_hackathons()
        assert published_hackathon not in results
        assert Hackathon.objects.filter(id=published_hackathon.id).exists()  # data preserved


class TestReactivateHackathon:
    def test_reactivates_and_logs_reason(self, platform_admin, suspended_hackathon):
        result = services.reactivate_hackathon(admin=platform_admin, hackathon_id=suspended_hackathon.id, reason="Investigation cleared")

        assert result.is_suspended is False
        entry = AuditLogEntry.objects.get(action="hackathon.reactivated", target_id=str(suspended_hackathon.id))
        assert entry.metadata["reason"] == "Investigation cleared"

    def test_not_suspended_raises(self, platform_admin, hackathon):
        with pytest.raises(ValidationError):
            services.reactivate_hackathon(admin=platform_admin, hackathon_id=hackathon.id, reason="x")


# ---------------------------------------------------------------------------
# FR-ADMIN-001: suspend / reactivate an organization
# ---------------------------------------------------------------------------


class TestSuspendOrganization:
    def test_suspends_and_logs_reason(self, platform_admin, organization):
        result = services.suspend_organization(admin=platform_admin, organization_id=organization.id, reason="Fake registration documents")

        assert result.is_suspended is True
        entry = AuditLogEntry.objects.get(action="organization.suspended", target_id=str(organization.id))
        assert entry.actor_id == platform_admin.id
        assert entry.metadata["reason"] == "Fake registration documents"

    def test_already_suspended_raises(self, platform_admin, suspended_organization):
        with pytest.raises(ValidationError):
            services.suspend_organization(admin=platform_admin, organization_id=suspended_organization.id, reason="again")

    def test_suspending_org_hides_its_hackathons_from_discovery(self, platform_admin, verified_organization):
        from apps.hackathons.services import list_hackathons
        from apps.hackathons.tests.factories import PublishedHackathonFactory

        hosted = PublishedHackathonFactory(host_org=verified_organization)

        services.suspend_organization(admin=platform_admin, organization_id=verified_organization.id, reason="Terms violation")

        results, total = list_hackathons()
        assert hosted not in results
        assert Organization.objects.filter(id=verified_organization.id).exists()  # data preserved


class TestReactivateOrganization:
    def test_reactivates_and_logs_reason(self, platform_admin, suspended_organization):
        result = services.reactivate_organization(admin=platform_admin, organization_id=suspended_organization.id, reason="Appeal accepted")

        assert result.is_suspended is False
        entry = AuditLogEntry.objects.get(action="organization.reactivated", target_id=str(suspended_organization.id))
        assert entry.metadata["reason"] == "Appeal accepted"

    def test_not_suspended_raises(self, platform_admin, organization):
        with pytest.raises(ValidationError):
            services.reactivate_organization(admin=platform_admin, organization_id=organization.id, reason="x")


# ---------------------------------------------------------------------------
# FR-ADMIN-001: suspend / reactivate a user account
# ---------------------------------------------------------------------------


class TestSuspendAccount:
    def test_suspends_bumps_token_version_and_logs_reason(self, platform_admin, regular_account):
        original_token_version = regular_account.token_version

        result = services.suspend_account(admin=platform_admin, user_id=regular_account.id, reason="Harassment reports")

        assert result.is_suspended is True
        assert result.token_version == original_token_version + 1  # NFR-SEC-005: revoke sessions
        assert result.is_active is False

        entry = AuditLogEntry.objects.get(action="account.suspended", target_id=str(regular_account.id))
        assert entry.actor_id == platform_admin.id
        assert entry.metadata["reason"] == "Harassment reports"

    def test_admin_cannot_suspend_own_account(self, platform_admin):
        with pytest.raises(ValidationError):
            services.suspend_account(admin=platform_admin, user_id=platform_admin.id, reason="x")

    def test_admin_can_suspend_another_admin(self, platform_admin, other_platform_admin):
        result = services.suspend_account(admin=platform_admin, user_id=other_platform_admin.id, reason="Compromised credentials")
        assert result.is_suspended is True

    def test_already_suspended_raises(self, platform_admin, regular_account):
        services.suspend_account(admin=platform_admin, user_id=regular_account.id, reason="first")
        with pytest.raises(ValidationError):
            services.suspend_account(admin=platform_admin, user_id=regular_account.id, reason="second")


class TestReactivateAccount:
    def test_reactivates_and_logs_reason(self, platform_admin, regular_account):
        services.suspend_account(admin=platform_admin, user_id=regular_account.id, reason="first")

        result = services.reactivate_account(admin=platform_admin, user_id=regular_account.id, reason="Appeal accepted")

        assert result.is_suspended is False
        assert result.is_active is True
        entry = AuditLogEntry.objects.get(action="account.reactivated", target_id=str(regular_account.id))
        assert entry.metadata["reason"] == "Appeal accepted"

    def test_not_suspended_raises(self, platform_admin, regular_account):
        with pytest.raises(ValidationError):
            services.reactivate_account(admin=platform_admin, user_id=regular_account.id, reason="x")


# ---------------------------------------------------------------------------
# FR-ADMIN-002: platform-wide search
# ---------------------------------------------------------------------------


class TestPlatformSearch:
    def test_finds_matching_user_by_name_or_email(self, platform_admin, regular_account):
        by_name = services.platform_search(admin=platform_admin, query=regular_account.full_name)
        assert regular_account in by_name["users"]

        by_email = services.platform_search(admin=platform_admin, query=regular_account.email)
        assert regular_account in by_email["users"]

    def test_finds_matching_organization_by_name(self, platform_admin, organization):
        results = services.platform_search(admin=platform_admin, query=organization.name)
        assert organization in results["organizations"]

    def test_finds_matching_hackathon_by_title(self, platform_admin, hackathon):
        results = services.platform_search(admin=platform_admin, query=hackathon.title)
        assert hackathon in results["hackathons"]

    def test_blank_query_raises_validation_error(self, platform_admin):
        with pytest.raises(ValidationError):
            services.platform_search(admin=platform_admin, query="   ")

    def test_every_query_is_logged(self, platform_admin):
        services.platform_search(admin=platform_admin, query="anything")

        entry = AuditLogEntry.objects.get(action="platform_admin.search")
        assert entry.actor_id == platform_admin.id
        assert entry.metadata["query"] == "anything"
