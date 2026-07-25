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


# Periodic tasks (submission-deadline reminders, 90-day in-app purge) are
# registered in CELERY_BEAT_SCHEDULE (config/settings/base.py) and defined
# in apps/notifications/tasks.py.