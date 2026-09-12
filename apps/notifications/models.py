"""
notifications -- models

Implements FR modules: NOTIFY
Depends on: core, hackathons, accounts

Per Design Spec Sec 3.1: data shape and database-level constraints ONLY.
No business logic here -- see services.py.

DB Design Sec 4.8 defines two tables:

- `notification` -- the logical message (what was said, in which channel).
- `notification_delivery` -- per-recipient fan-out and status, kept
  separate so a single broadcast (e.g. a deadline reminder to every
  registrant) doesn't require one `notification` row per recipient, and
  so NFR-PERF-003 (60s email SLA) / NFR-AVAIL-003 (SMS-failure isolation)
  are each independently measurable per delivery.

Neither table declares a NOT NULL `hackathon_id`/tenant column the way
Registration/Team/Submission do (DB Design Sec 4.8's `notification.
hackathon_id` has no NOT NULL), so neither uses TenantScopedManager --
same reasoning as organizations.Organization being a tenant root rather
than a tenant-scoped model (Design Spec Sec 3.3). A user's own
notification feed is scoped by `user_id` in services.py instead (see
services.list_my_notifications), the same "ownership query, not a
cross-tenant listing" category the module docstring on
core.managers.TenantScopedManager carves out for by-primary-key lookups.
"""

import uuid

from django.db import models

CHANNEL_CHOICES = [
    ("email", "Email"),
    ("in_portal", "In-Portal"),
    ("sms", "SMS"),
]

DELIVERY_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("sent", "Sent"),
    ("failed", "Failed"),
]


class Notification(models.Model):
    """The logical message -- FR-NOTIFY-001/002 (DB Design Sec 4.8).

    `channel` is singular per row: an event that fans out over more than
    one channel (e.g. a deadline reminder sent by both email and
    in-portal per FR-NOTIFY-001) is modeled as one Notification row per
    channel, each with its own set of NotificationDelivery rows -- not
    one row with a list of channels. This keeps `channel` a plain scalar
    matching DB Design's `CHECK (channel IN (...))` column exactly.

    `hackathon` is nullable per DB Design Sec 4.8. Every FR-NOTIFY-001
    event this app currently sends happens to have a hackathon in
    context, but the column is left nullable to match the documented
    schema rather than tightening it without a spec basis.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hackathon = models.ForeignKey(
        "hackathons.Hackathon", on_delete=models.CASCADE, null=True, blank=True,
        related_name="notifications",
    )
    title = models.CharField(max_length=255, blank=True, default="")
    category = models.CharField(max_length=50, blank=True, default="")
    message = models.TextField()
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "notifications"
        indexes = [models.Index(fields=["hackathon"])]

    def __str__(self):
        return f"Notification({self.channel}): {self.message[:40]}"


class NotificationDelivery(models.Model):
    """Per-recipient fan-out and delivery status (DB Design Sec 4.8).

    `read_at` is NOT in DB Design Sec 4.8's column list -- that table
    only has `status` (pending/sent/failed), which tracks whether the
    message left the platform, not whether the recipient has seen it.
    FR-NOTIFY-001's acceptance criterion ("marked unread until the user
    views the notification center") has no other column to hang off of,
    so this is added the same way accounts.Account.profile_visibility
    was added beyond Doc 05 "to make the FR enforceable" -- see that
    model's inline comment for the precedent. Only meaningful for
    `channel="in_portal"` rows; email/SMS deliveries never populate it.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="deliveries",
    )
    user = models.ForeignKey(
        "accounts.Account", on_delete=models.CASCADE, related_name="notification_deliveries",
    )
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES)
    status = models.CharField(max_length=20, choices=DELIVERY_STATUS_CHOICES, default="pending")
    sent_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    read_at = models.DateTimeField(null=True, blank=True)  # see class docstring

    class Meta:
        app_label = "notifications"
        indexes = [
            models.Index(fields=["notification"]),
            models.Index(fields=["user", "status"]),  # a user's in-portal feed, DB Design Sec 4.8
        ]

    def __str__(self):
        return f"{self.user_id} <- {self.notification_id} ({self.channel}, {self.status})"
