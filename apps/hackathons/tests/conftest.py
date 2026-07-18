"""
Shared fixtures for apps.hackathons.tests. `django_db` applied once here,
same pattern as apps/organizations/tests/conftest.py.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import RoleAssignment
from apps.accounts.tests.factories import AccountFactory
from apps.organizations.tests.factories import VerifiedOrganizationFactory

from .factories import HackathonFactory, PublishedHackathonFactory


@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    """Applies django_db to every test in this package."""


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
def organizer_account():
    return AccountFactory()


@pytest.fixture
def verified_org(organizer_account):
    return VerifiedOrganizationFactory(created_by=organizer_account)


@pytest.fixture
def organizer_role(organizer_account, verified_org):
    """Grants organizer_account the Organizer role scoped to verified_org."""
    return RoleAssignment.objects.create(
        user=organizer_account, role="organizer", scope_type="organization", scope_id=verified_org.id,
    )


@pytest.fixture
def hackathon(verified_org, organizer_account):
    return HackathonFactory(host_org=verified_org, created_by=organizer_account)


@pytest.fixture
def published_hackathon(verified_org, organizer_account):
    return PublishedHackathonFactory(host_org=verified_org, created_by=organizer_account)


@pytest.fixture
def other_account():
    """An authenticated actor with no RoleAssignment for `verified_org`."""
    return AccountFactory()