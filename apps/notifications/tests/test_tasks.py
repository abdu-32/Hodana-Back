"""Tests for apps.notifications.tasks -- the Celery Beat wrappers."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.hackathons.tests.factories import PublishedHackathonFactory
from apps.registrations.tests.factories import RegistrationFactory

from .. import tasks
from ..models import Notification, NotificationDelivery
from .factories import NotificationDeliveryFactory, NotificationFactory

pytestmark = pytest.mark.django_db


class TestSendSubmissionDeadlineReminders:
    def test_notifies_hackathon_23_to_24_hours_from_deadline(self, mailoutbox):
        in_window = PublishedHackathonFactory(
            submission_opens_at=timezone.now(),
            submission_closes_at=timezone.now() + timedelta(hours=23, minutes=30),
        )
        registration = RegistrationFactory(hackathon=in_window)

        sent = tasks.send_submission_deadline_reminders()

        assert sent == 1
        assert NotificationDelivery.objects.filter(user=registration.user, channel="email").exists()

    def test_ignores_hackathons_outside_the_window(self):
        too_soon = PublishedHackathonFactory(
            submission_opens_at=timezone.now(),
            submission_closes_at=timezone.now() + timedelta(hours=2),
        )
        too_far = PublishedHackathonFactory(submission_closes_at=timezone.now() + timedelta(days=10))
        RegistrationFactory(hackathon=too_soon)
        RegistrationFactory(hackathon=too_far)

        sent = tasks.send_submission_deadline_reminders()

        assert sent == 0
        assert not NotificationDelivery.objects.exists()

    def test_ignores_unpublished_hackathons(self):
        from apps.hackathons.tests.factories import HackathonFactory

        draft = HackathonFactory(
            status="draft",
            submission_opens_at=timezone.now(),
            submission_closes_at=timezone.now() + timedelta(hours=23, minutes=30),
        )
        RegistrationFactory(hackathon=draft)

        sent = tasks.send_submission_deadline_reminders()

        assert sent == 0


class TestPurgeExpiredInAppNotificationsTask:
    def test_deletes_deliveries_older_than_90_days(self):
        from apps.accounts.tests.factories import AccountFactory

        user = AccountFactory()
        old_notification = NotificationFactory(channel="in_portal")
        Notification.objects.filter(id=old_notification.id).update(
            created_at=timezone.now() - timedelta(days=91),
        )
        old_delivery = NotificationDeliveryFactory(user=user, channel="in_portal", notification=old_notification)
        recent_delivery = NotificationDeliveryFactory(user=user, channel="in_portal")

        deleted_count = tasks.purge_expired_in_app_notifications_task()

        assert deleted_count >= 1
        remaining_ids = set(NotificationDelivery.objects.values_list("id", flat=True))
        assert old_delivery.id not in remaining_ids
        assert recent_delivery.id in remaining_ids