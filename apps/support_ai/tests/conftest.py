import pytest
from rest_framework.test import APIClient
from apps.accounts.tests.factories import AccountFactory


from rest_framework_simplejwt.tokens import RefreshToken

@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    pass


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def platform_admin():
    return AccountFactory(is_platform_admin=True)


@pytest.fixture
def regular_user():
    return AccountFactory(is_platform_admin=False)


@pytest.fixture
def auth_headers():
    def _make(account):
        token = RefreshToken.for_user(account)
        token["token_version"] = account.token_version
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}
    return _make
