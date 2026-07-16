"""
Shared fixtures for apps.accounts.tests. Every test in this package hits
the database (services.py is tested against real models per Document 07
Sec 2's unit-test row), so `django_db` is applied here once rather than
per-test.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .factories import DEFAULT_PASSWORD, AccountFactory, PrivateAccountFactory, UnverifiedAccountFactory


@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(db):
    """Applies django_db to every test in this package without each test
    module needing its own `pytestmark = pytest.mark.django_db` line."""


@pytest.fixture
def raw_password():
    return DEFAULT_PASSWORD


@pytest.fixture
def verified_account(raw_password):
    return AccountFactory(password=raw_password)


@pytest.fixture
def unverified_account(raw_password):
    return UnverifiedAccountFactory(password=raw_password)


@pytest.fixture
def private_account(raw_password):
    return PrivateAccountFactory(password=raw_password)

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