"""
Shared fixtures for apps.platform_admin.tests. `django_db` applied once
here, same pattern as apps/organizations/tests/conftest.py and
apps/hackathons/tests/conftest.py.

No apps/platform_admin/tests/factories.py -- this app owns no models of
its own (see models.py), so every fixture below is built from factories
that already exist in the apps that do own the underlying rows.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.tests.factories import AccountFactory
from apps.hackathons.tests.factories import HackathonFactory, PublishedHackathonFactory
from apps.organizations.tests.factories import OrganizationFactory, PendingOrganizationFactory, VerifiedOrganizationFactory


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
def platform_admin():
    """The only actor allowed to call anything in this module."""
    return AccountFactory(is_platform_admin=True)


@pytest.fixture
def other_platform_admin():
    """A second admin -- used by the "admin can't suspend own account"
    test, which needs an admin acting on someone OTHER than themself."""
    return AccountFactory(is_platform_admin=True)


@pytest.fixture
def regular_account():
    """A non-admin actor -- every endpoint in this module must reject
    this with 403 (FR-ADMIN-001/002's shared precondition)."""
    return AccountFactory()


@pytest.fixture
def organization():
    return OrganizationFactory()


@pytest.fixture
def pending_organization():
    return PendingOrganizationFactory()


@pytest.fixture
def verified_organization():
    return VerifiedOrganizationFactory()


@pytest.fixture
def suspended_organization():
    return OrganizationFactory(is_suspended=True)


@pytest.fixture
def hackathon():
    return HackathonFactory()


@pytest.fixture
def published_hackathon():
    return PublishedHackathonFactory()


@pytest.fixture
def suspended_hackathon():
    return PublishedHackathonFactory(is_suspended=True)
