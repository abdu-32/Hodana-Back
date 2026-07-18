"""
factory-boy factories for apps.hackathons models.
"""

from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import AccountFactory
from apps.organizations.tests.factories import VerifiedOrganizationFactory

from ..models import ChallengeTrack, Hackathon


class HackathonFactory(DjangoModelFactory):
    """Defaults to a `draft` hackathon owned by a verified organization,
    with a valid, non-overlapping timeline -- the shape most tests want
    before exercising FR-HACK-005's publish gate."""

    class Meta:
        model = Hackathon

    host_org = factory.SubFactory(VerifiedOrganizationFactory)
    title = factory.Sequence(lambda n: f"Test Hackathon {n}")
    slug = factory.Sequence(lambda n: f"test-hackathon-{n}")
    description = "A test hackathon."
    registration_opens_at = factory.LazyFunction(timezone.now)
    registration_closes_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=7))
    submission_opens_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=7))
    submission_closes_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=14))
    location_mode = "online"
    eligibility_rules = factory.LazyFunction(lambda: {"min_team_size": 1, "max_team_size": 4})
    tags = factory.LazyFunction(list)
    status = "draft"
    created_by = factory.SubFactory(AccountFactory)


class PublishedHackathonFactory(HackathonFactory):
    status = "published"


class ArchivedHackathonFactory(HackathonFactory):
    """Already past its end date -- the shape needed for tests asserting
    a valid archive transition."""

    status = "archived"
    registration_opens_at = factory.LazyFunction(lambda: timezone.now() - timedelta(days=15))
    registration_closes_at = factory.LazyFunction(lambda: timezone.now() - timedelta(days=8))
    submission_opens_at = factory.LazyFunction(lambda: timezone.now() - timedelta(days=8))
    submission_closes_at = factory.LazyFunction(lambda: timezone.now() - timedelta(days=1))


class ChallengeTrackFactory(DjangoModelFactory):
    class Meta:
        model = ChallengeTrack

    hackathon = factory.SubFactory(HackathonFactory)
    sponsor_org = factory.SubFactory(VerifiedOrganizationFactory)
    name = factory.Sequence(lambda n: f"Track {n}")
    description = "A test track."
    prize = "$500"