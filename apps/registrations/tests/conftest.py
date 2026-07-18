import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone
from datetime import timedelta

from apps.accounts.tests.factories import AccountFactory
from apps.hackathons.tests.factories import PublishedHackathonFactory

from .factories import RegistrationFactory


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
def participant():
    return AccountFactory()


@pytest.fixture
def published_hackathon():
    """Registration window already open by a comfortable margin, not
    exactly 'now' -- PublishedHackathonFactory's own default puts
    registration_opens_at at the instant the row is built, which leaves
    zero margin against the service's own now() check a moment later and
    is a source of rare timing-dependent test failures under load."""
    return PublishedHackathonFactory(
        registration_opens_at=timezone.now() - timedelta(hours=1),
        registration_closes_at=timezone.now() + timedelta(days=7),
        submission_opens_at=timezone.now() + timedelta(days=7),
        submission_closes_at=timezone.now() + timedelta(days=14),
    )


@pytest.fixture
def registration(participant, published_hackathon):
    return RegistrationFactory(user=participant, hackathon=published_hackathon)