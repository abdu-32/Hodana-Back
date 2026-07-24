"""
Celery application entrypoint.

Per Design Spec Sec 8.1: Celery Worker replicas scale freely (jobs are
idempotent/safely retryable); Celery Beat runs as exactly one replica
(it is a scheduler — a second replica would duplicate every periodic job,
e.g. double-sending deadline reminders). This file is shared by both;
the difference is only the CMD used in docker-compose (worker vs beat).
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("innovation_hub")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


# TODO(notifications): once Celery Beat is enabled, add a periodic task
# to CELERY_BEAT_SCHEDULE that calls
# apps.notifications.services.notify_submission_deadline_reminder(hackathon)
# ~24h before each hackathon's submission_closes_at (FR-NOTIFY-001/002).
# The function itself is already implemented and tested -- it just has
# no scheduler to call it yet. Same applies to
# apps.notifications.services.purge_expired_in_app_notifications() for
# the 90-day in-app retention rule -- run it daily.