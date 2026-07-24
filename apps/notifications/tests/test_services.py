"""
Unit tests against notifications/services.py directly (Design Spec Sec 3.1),
per the 80% coverage target in NFR-MAINT-001. Prefer these over
HTTP-level tests for business-rule coverage.
"""

import pytest
from rest_framework.exceptions import NotFound, PermissionDenied

from apps.accounts.tests.factories import AccountFactory
from apps.registrations.tests.factories import RegistrationFactory, WithdrawnRegistrationFactory
from apps.teams.tests.factories import AcceptedTeamMemberFactory, TeamFactory, TeamMemberFactory

from .. import services
from ..models import Notification, NotificationDelivery
from .factories import NotificationDeliveryFactory, NotificationFactory

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# notify_users -- the core fan-out
# ---------------------------------------------------------------------------


class TestNotifyUsers:
    def test_creates_one_notification_per_channel(self, hackathon, participant, mailoutbox):
        notifications = services.notify_users(
            category="hackathon_timeline_change",
            hackathon=hackathon,
            recipients=[participant],
            subject="Subject",
            message="Body",
            channels=("email", "in_portal"),
        )

        assert len(notifications) == 2
        assert {n.channel for n in notifications} == {"email", "in_portal"}
        assert Notification.objects.filter(hackathon=hackathon).count() == 2

    def test_creates_one_delivery_per_recipient_per_channel(self, hackathon):
        alice, bob = AccountFactory(), AccountFactory()

        services.notify_users(
            category="hackathon_timeline_change",
            hackathon=hackathon,
            recipients=[alice, bob],
            subject="Subject",
            message="Body",
            channels=("email", "in_portal"),
        )

        assert NotificationDelivery.objects.filter(channel="email").count() == 2
        assert NotificationDelivery.objects.filter(channel="in_portal").count() == 2

    def test_email_delivery_is_sent_and_marked_sent(self, hackathon, participant, mailoutbox):
        services.notify_users(
            category="hackathon_timeline_change",
            hackathon=hackathon,
            recipients=[participant],
            subject="Subject line",
            message="Body text",
            channels=("email",),
        )

        assert len(mailoutbox) == 1
        assert mailoutbox[0].subject == "Subject line"
        delivery = NotificationDelivery.objects.get(channel="email")
        assert delivery.status == "sent"
        assert delivery.sent_at is not None

    def test_in_portal_delivery_is_sent_and_unread(self, hackathon, participant):
        services.notify_users(
            category="hackathon_timeline_change",
            hackathon=hackathon,
            recipients=[participant],
            subject="Subject",
            message="Body",
            channels=("in_portal",),
        )

        delivery = NotificationDelivery.objects.get(channel="in_portal")
        assert delivery.status == "sent"
        assert delivery.read_at is None

    def test_no_recipients_creates_nothing(self, hackathon):
        notifications = services.notify_users(
            category="hackathon_timeline_change",
            hackathon=hackathon,
            recipients=[],
            subject="Subject",
            message="Body",
        )

        assert notifications == []
        assert Notification.objects.count() == 0

    def test_sms_is_a_documented_gap_and_creates_no_sms_rows(self, hackathon, participant):
        """FR-NOTIFY-002: Account has no phone number field, so SMS is a
        known gap (see services._send_sms_fallback) -- requesting it
        should not blow up, and should not fabricate sms rows either."""
        services.notify_users(
            category="submission_deadline_reminder",
            hackathon=hackathon,
            recipients=[participant],
            subject="Subject",
            message="Body",
            channels=("email", "in_portal"),
            sms=True,
        )

        assert NotificationDelivery.objects.filter(channel="sms").count() == 0

    def test_email_failure_is_isolated_per_recipient(self, hackathon, participant, monkeypatch):
        """A failure sending to one recipient is recorded on that
        delivery, not raised -- so one bad address doesn't take the rest
        of a broadcast down with it (NFR-AVAIL-003's isolation
        principle, applied to email instead of SMS)."""
        def _boom(**kwargs):
            raise RuntimeError("smtp exploded")

        monkeypatch.setattr(services, "send_mail", _boom)

        services.notify_users(
            category="hackathon_timeline_change",
            hackathon=hackathon,
            recipients=[participant],
            subject="Subject",
            message="Body",
            channels=("email",),
        )

        delivery = NotificationDelivery.objects.get(channel="email")
        assert delivery.status == "failed"
        assert "smtp exploded" in delivery.failure_reason


# ---------------------------------------------------------------------------
# Event wrappers
# ---------------------------------------------------------------------------


class TestNotifyRegistrationConfirmed:
    def test_notifies_only_the_registrant(self, registration, mailoutbox):
        services.notify_registration_confirmed(registration)

        assert len(mailoutbox) == 1
        assert mailoutbox[0].to == [registration.user.contact_email or registration.user.email]
        assert NotificationDelivery.objects.filter(channel="in_portal", user=registration.user).exists()


class TestNotifyHackathonTimelineChanged:
    def test_notifies_active_registrants_only(self, hackathon):
        active = RegistrationFactory(hackathon=hackathon)
        withdrawn = WithdrawnRegistrationFactory(hackathon=hackathon)

        services.notify_hackathon_timeline_changed(hackathon)

        notified_users = set(NotificationDelivery.objects.filter(channel="in_portal").values_list("user_id", flat=True))
        assert active.user_id in notified_users
        assert withdrawn.user_id not in notified_users

    def test_no_registrants_creates_no_notification(self, hackathon):
        notifications = services.notify_hackathon_timeline_changed(hackathon)
        assert notifications == []


class TestNotifyTeamInvitation:
    def test_notifies_the_invitee(self, hackathon, participant):
        team = TeamFactory(hackathon=hackathon)
        member = TeamMemberFactory(team=team, hackathon=hackathon, user=participant)

        services.notify_team_invitation(member)

        assert NotificationDelivery.objects.filter(user=participant, channel="in_portal").exists()

    def test_invitee_with_no_account_is_a_known_gap_not_an_error(self, hackathon):
        """DB Design Sec 4.5: invitee_email-only rows (user=None) can't
        be filed against the required NotificationDelivery.user FK."""
        team = TeamFactory(hackathon=hackathon)
        member = TeamMemberFactory(
            team=team, hackathon=hackathon, user=None, invitee_email="invitee@example.com",
        )

        result = services.notify_team_invitation(member)

        assert result == []
        assert NotificationDelivery.objects.count() == 0


class TestNotifyInvitationResponse:
    def test_notifies_the_team_leader(self, hackathon):
        owner = AccountFactory()
        team = TeamFactory(hackathon=hackathon, leader_user=owner)
        invitee = AccountFactory()
        member = AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=invitee)

        services.notify_invitation_response(member)

        assert NotificationDelivery.objects.filter(user=owner, channel="in_portal").exists()

    def test_leader_accepting_their_own_row_notifies_no_one(self, hackathon):
        owner = AccountFactory()
        team = TeamFactory(hackathon=hackathon, leader_user=owner)
        member = AcceptedTeamMemberFactory(team=team, hackathon=hackathon, user=owner)

        result = services.notify_invitation_response(member)

        assert result == []


class TestNotifySubmissionDeadlineReminder:
    def test_is_sent_to_active_registrants_and_attempts_sms(self, hackathon, mailoutbox):
        registration = RegistrationFactory(hackathon=hackathon)

        services.notify_submission_deadline_reminder(hackathon)

        assert NotificationDelivery.objects.filter(user=registration.user, channel="email").exists()
        assert NotificationDelivery.objects.filter(user=registration.user, channel="in_portal").exists()
        assert not NotificationDelivery.objects.filter(channel="sms").exists()


class TestNotifyJudgingResultsPublished:
    def test_is_sent_to_active_registrants(self, hackathon):
        registration = RegistrationFactory(hackathon=hackathon)

        services.notify_judging_results_published(hackathon)

        assert NotificationDelivery.objects.filter(user=registration.user, channel="in_portal").exists()


# ---------------------------------------------------------------------------
# create_announcement -- POST /notifications
# ---------------------------------------------------------------------------


class TestCreateAnnouncement:
    def test_organizer_can_broadcast(self, organizer_account, organizer_role, hackathon, registration, mailoutbox):
        notification = services.create_announcement(
            actor=organizer_account, hackathon_id=hackathon.id, message="Hello all", channel="email",
        )

        assert notification.channel == "email"
        assert notification.message == "Hello all"
        assert NotificationDelivery.objects.filter(user=registration.user, channel="email").exists()
        assert len(mailoutbox) == 1

    def test_non_organizer_is_denied(self, hackathon, participant):
        with pytest.raises(PermissionDenied):
            services.create_announcement(
                actor=participant, hackathon_id=hackathon.id, message="Hello", channel="email",
            )

    def test_nonexistent_hackathon_raises_not_found(self, organizer_account):
        import uuid
        with pytest.raises(NotFound):
            services.create_announcement(
                actor=organizer_account, hackathon_id=uuid.uuid4(), message="Hello", channel="email",
            )


# ---------------------------------------------------------------------------
# Notification center
# ---------------------------------------------------------------------------


class TestListMyNotifications:
    def test_returns_only_the_requesters_in_portal_deliveries(self, participant):
        mine = NotificationDeliveryFactory(user=participant, channel="in_portal")
        NotificationDeliveryFactory(user=AccountFactory(), channel="in_portal")  # someone else's

        results = list(services.list_my_notifications(actor=participant))

        assert [d.id for d in results] == [mine.id]

    def test_unread_only_filter(self, participant):
        from django.utils import timezone

        unread = NotificationDeliveryFactory(user=participant, channel="in_portal")
        NotificationDeliveryFactory(user=participant, channel="in_portal", read_at=timezone.now())

        results = list(services.list_my_notifications(actor=participant, unread_only=True))

        assert [d.id for d in results] == [unread.id]

    def test_excludes_email_deliveries(self, participant):
        NotificationDeliveryFactory(user=participant, channel="email")

        results = list(services.list_my_notifications(actor=participant))

        assert results == []


class TestMarkNotificationRead:
    def test_marks_read_and_is_idempotent(self, participant):
        delivery = NotificationDeliveryFactory(user=participant, channel="in_portal")

        first = services.mark_notification_read(actor=participant, delivery_id=delivery.id)
        assert first.read_at is not None

        second = services.mark_notification_read(actor=participant, delivery_id=delivery.id)
        assert second.read_at == first.read_at

    def test_another_users_delivery_is_not_reachable(self, participant):
        other_delivery = NotificationDeliveryFactory(user=AccountFactory(), channel="in_portal")

        with pytest.raises(NotFound):
            services.mark_notification_read(actor=participant, delivery_id=other_delivery.id)


class TestPurgeExpiredInAppNotifications:
    def test_deletes_only_deliveries_older_than_90_days(self, participant):
        from datetime import timedelta
        from django.utils import timezone

        old_notification = NotificationFactory(channel="in_portal")
        Notification.objects.filter(id=old_notification.id).update(
            created_at=timezone.now() - timedelta(days=91),
        )
        old_delivery = NotificationDeliveryFactory(
            user=participant, channel="in_portal", notification=old_notification,
        )
        recent_delivery = NotificationDeliveryFactory(user=participant, channel="in_portal")

        services.purge_expired_in_app_notifications()

        remaining_ids = set(NotificationDelivery.objects.values_list("id", flat=True))
        assert old_delivery.id not in remaining_ids
        assert recent_delivery.id in remaining_ids
