"""
notifications -- Celery tasks

Thin scheduler-facing wrappers around the two apps.notifications.services
functions that were already implemented and tested but had nothing calling
them (see config/settings/base.py CELERY_BEAT_SCHEDULE for the cadence).

Kept deliberately thin: all business logic stays in services.py, unit-
tested there without needing a Celery worker. These wrappers only handle
"what to call, on what set of rows, on a schedule."
"""

from celery import shared_task
from django.utils import timezone

from .services import notify_submission_deadline_reminder, purge_expired_in_app_notifications


@shared_task(name="apps.notifications.tasks.send_submission_deadline_reminders")
def send_submission_deadline_reminders():
    """FR-NOTIFY-001/002: fires once per published hackathon whose
    submission_closes_at falls 23-24 hours from now.

    Runs hourly (CELERY_BEAT_SCHEDULE). The 23-24h window is deliberately
    narrow and matched to the hourly cadence so a given hackathon's
    deadline passes through the window exactly once -- this is what
    keeps the job idempotent without needing a `reminder_sent_at` column
    on Hackathon. If the beat schedule's interval ever changes, this
    window must change with it (window width == schedule interval).
    """
    from apps.hackathons.models import Hackathon

    now = timezone.now()
    window_start = now + timezone.timedelta(hours=23)
    window_end = now + timezone.timedelta(hours=24)

    hackathons = Hackathon.objects.filter(
        status="published",
        submission_closes_at__gte=window_start,
        submission_closes_at__lt=window_end,
    )

    sent = 0
    for hackathon in hackathons:
        notify_submission_deadline_reminder(hackathon)
        sent += 1
    return sent


@shared_task(name="apps.notifications.tasks.purge_expired_in_app_notifications_task")
def purge_expired_in_app_notifications_task():
    """FR-NOTIFY-001: daily purge of in-app notifications older than the
    90-day retention window (CELERY_BEAT_SCHEDULE runs this once/day)."""
    deleted_count, _ = purge_expired_in_app_notifications()
    return deleted_count