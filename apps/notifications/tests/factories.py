"""factory-boy factories for apps.notifications models."""

import factory
from factory.django import DjangoModelFactory

from apps.accounts.tests.factories import AccountFactory
from apps.hackathons.tests.factories import PublishedHackathonFactory

from ..models import Notification, NotificationDelivery


class NotificationFactory(DjangoModelFactory):
    class Meta:
        model = Notification

    hackathon = factory.SubFactory(PublishedHackathonFactory)
    message = "Test notification message."
    channel = "in_portal"


class NotificationDeliveryFactory(DjangoModelFactory):
    class Meta:
        model = NotificationDelivery

    notification = factory.SubFactory(NotificationFactory)
    user = factory.SubFactory(AccountFactory)
    channel = "in_portal"
    status = "sent"
