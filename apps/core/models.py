"""
core.models -- shared kernel

Per Design Spec Sec 3.2: audit log, base abstract models, i18n helpers.
No other app should duplicate these.
"""

from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class AuditLogEntry(TimeStampedModel):
    """Cross-cutting audit trail, written to by services.py in other apps."""

    actor_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100)
    target_id = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        app_label = "core"
        indexes = [models.Index(fields=["target_type", "target_id"])]
