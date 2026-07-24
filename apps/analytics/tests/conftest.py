import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import RoleAssignment
from apps.accounts.tests.factories import AccountFactory
from apps.hackathons.tests.factories import PublishedHackathonFactory
from apps.organizations.tests.factories import VerifiedOrganizationFactory


@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    pass


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
    return RoleAssignment.objects.create(
        user=organizer_account,
        role="organizer",
        scope_type="organization",
        scope_id=verified_org.id,
    )


@pytest.fixture
def hackathon(verified_org, organizer_account, organizer_role):
    return PublishedHackathonFactory(host_org=verified_org, created_by=organizer_account)


@pytest.fixture
def platform_admin_account():
    return AccountFactory(is_platform_admin=True)
