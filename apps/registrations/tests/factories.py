"""factory-boy factories for apps.registrations models."""

import factory
from factory.django import DjangoModelFactory
from django.utils import timezone

from apps.accounts.tests.factories import AccountFactory
from apps.hackathons.tests.factories import PublishedHackathonFactory

from ..models import Registration


class RegistrationFactory(DjangoModelFactory):
    class Meta:
        model = Registration

    hackathon = factory.SubFactory(PublishedHackathonFactory)
    user = factory.SubFactory(AccountFactory)
    eligibility_confirmed = True


class WithdrawnRegistrationFactory(RegistrationFactory):
    withdrawn_at = factory.LazyFunction(timezone.now)