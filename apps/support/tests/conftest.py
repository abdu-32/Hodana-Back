import pytest
from rest_framework.test import APIClient
from apps.accounts.tests.factories import AccountFactory
from apps.support.tests.factories import TicketFactory

@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    pass

@pytest.fixture
def api_client():
    return APIClient()

@pytest.fixture
def staff_user():
    return AccountFactory(is_staff=True)

@pytest.fixture
def regular_user():
    return AccountFactory()

@pytest.fixture
def ticket(regular_user):
    return TicketFactory(submitter=regular_user)

@pytest.fixture
def auth_headers(regular_user):
    from rest_framework_simplejwt.tokens import RefreshToken
    token = RefreshToken.for_user(regular_user)
    token["token_version"] = regular_user.token_version
    return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}
