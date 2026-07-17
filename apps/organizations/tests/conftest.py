"""
Shared fixtures for apps.organizations.tests. Every test in this package
hits the database (services.py is tested against real models per
Document 07 Sec 2's unit-test row), so `django_db` is applied here once
rather than per-test -- same pattern as apps/accounts/tests/conftest.py.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import RoleAssignment
from apps.accounts.tests.factories import AccountFactory, UnverifiedAccountFactory

from .factories import OrganizationFactory, PendingOrganizationFactory, VerifiedOrganizationFactory


@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    """Applies django_db to every test in this package without each test
    module needing its own `pytestmark = pytest.mark.django_db` line."""


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_headers():
    def _make(account):
        token = RefreshToken.for_user(account)
        token["token_version"] = account.token_version
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}
    return _make


@pytest.fixture
def verified_account():
    """A generic verified actor -- FR-ORG-001 requires this to register
    an organization at all."""
    return AccountFactory()


@pytest.fixture
def unverified_account():
    """FR-ORG-001: an unverified actor must be rejected by
    register_organization."""
    return UnverifiedAccountFactory()


@pytest.fixture
def platform_admin():
    """FR-ORG-003: the only actor allowed to call
    review_organization_verification."""
    return AccountFactory(is_platform_admin=True)


@pytest.fixture
def organization(verified_account):
    """An `unverified` org with no declared domain, owned by
    verified_account -- but note this bypasses services.register_organization,
    so no matching RoleAssignment exists yet. Combine with `organizer_role`
    below for tests where the actor needs to act as this org's Organizer."""
    return OrganizationFactory(created_by=verified_account)


@pytest.fixture
def pending_organization(verified_account):
    return PendingOrganizationFactory(created_by=verified_account)


@pytest.fixture
def verified_organization(verified_account):
    return VerifiedOrganizationFactory(created_by=verified_account)


@pytest.fixture
def organizer_role(verified_account, organization):
    """Grants verified_account the Organizer role scoped to `organization`
    -- mirrors what services.register_organization creates automatically
    on a real registration, exposed separately here for tests that build
    the org directly via the factory instead."""
    return RoleAssignment.objects.create(
        user=verified_account,
        role="organizer",
        scope_type="organization",
        scope_id=organization.id,
    )