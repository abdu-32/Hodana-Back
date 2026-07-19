from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.tests.factories import AccountFactory
from apps.hackathons.tests.factories import PublishedHackathonFactory
from apps.registrations.tests.factories import RegistrationFactory
from apps.teams.tests.factories import AcceptedTeamMemberFactory, TeamFactory


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
def owner():
    return AccountFactory()


@pytest.fixture
def hackathon():
    """Submission window open, deadline comfortably in the future -- same
    margin reasoning as apps.teams.tests.conftest.hackathon."""
    return PublishedHackathonFactory(
        registration_opens_at=timezone.now() - timedelta(days=7),
        registration_closes_at=timezone.now() - timedelta(days=1),
        submission_opens_at=timezone.now() - timedelta(hours=1),
        submission_closes_at=timezone.now() + timedelta(days=7),
        eligibility_rules={"min_team_size": 1, "max_team_size": 4},
    )


@pytest.fixture
def owner_registration(owner, hackathon):
    return RegistrationFactory(user=owner, hackathon=hackathon)


@pytest.fixture
def team(owner, hackathon, owner_registration):
    """A team owned by `owner`, with `owner` as its sole accepted member --
    the shape most submission tests want."""
    t = TeamFactory(hackathon=hackathon, leader_user=owner, max_size=4)
    AcceptedTeamMemberFactory(team=t, hackathon=hackathon, user=owner)
    return t