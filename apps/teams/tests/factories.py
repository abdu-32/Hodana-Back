"""factory-boy factories for apps.teams models."""

from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import AccountFactory
from apps.hackathons.tests.factories import PublishedHackathonFactory

from ..models import Team, TeamMember


class TeamFactory(DjangoModelFactory):
    class Meta:
        model = Team

    hackathon = factory.SubFactory(PublishedHackathonFactory)
    team_name = factory.Sequence(lambda n: f"Team {n}")
    leader_user = factory.SubFactory(AccountFactory)
    max_size = 4


class TeamMemberFactory(DjangoModelFactory):
    """Defaults to a pending invitation -- use AcceptedTeamMemberFactory
    for an already-joined roster row."""

    class Meta:
        model = TeamMember

    team = factory.SubFactory(TeamFactory)
    hackathon = factory.LazyAttribute(lambda o: o.team.hackathon)
    user = factory.SubFactory(AccountFactory)
    invitee_email = factory.LazyAttribute(lambda o: o.user.email)
    join_status = "pending"
    expires_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=7))


class AcceptedTeamMemberFactory(TeamMemberFactory):
    join_status = "accepted"
    responded_at = factory.LazyFunction(timezone.now)