"""
registrations -- models

Implements FR modules: REG
Depends on: hackathons, accounts

Per Design Spec Sec 3.1: data shape and database-level constraints ONLY.
No business logic here -- see services.py.

Per Design Spec Sec 3.3: every tenant-scoped model must use
TenantScopedManager from apps.core and declare its scoping field.

DB Design Sec 4.4's `registration` table has no created_at/updated_at
columns, so this doesn't use TimeStampedModel -- same pattern as
organizations.OrgVerificationReview and hackathons.ChallengeTrack.
"""

import uuid

from django.db import models

from apps.core.managers import TenantScopedManager

VERIFICATION_STATUS_CHOICES = [
    ("unverified", "Unverified"),
    ("pending", "Pending"),
    ("verified", "Verified"),
]


class RegistrationManager(TenantScopedManager):
    scope_field = "hackathon"


class Registration(models.Model):
    """Implements FR-REG-001..003 (DB Design Sec 4.4).

    `status` (registered/withdrawn) is not a stored column -- DB Design
    doesn't define one, only `withdrawn_at`. Derived as a property instead
    of a redundant field that could drift out of sync.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hackathon = models.ForeignKey(
        "hackathons.Hackathon", on_delete=models.CASCADE, related_name="registrations",
    )  # tenant-scoping column, Design Spec Sec 3.3
    user = models.ForeignKey(
        "accounts.Account", on_delete=models.CASCADE, related_name="registrations",
    )

    eligibility_confirmed = models.BooleanField(default=False)
    custom_answers = models.JSONField(null=True, blank=True)

    # FR-HACK-003's institutional-verification flavor of eligibility;
    # meaningful only where hackathon.eligibility_rules requires it
    # (DB Design Sec 4.4 note). Distinct from Account.verification_status.
    verification_status = models.CharField(
        max_length=20, choices=VERIFICATION_STATUS_CHOICES, default="unverified"
    )

    registered_at = models.DateTimeField(auto_now_add=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)  # FR-REG-002; row retained, not deleted

    objects = RegistrationManager()

    class Meta:
        app_label = "registrations"
        constraints = [
            # Schema-level enforcement of "one registration per user per
            # hackathon" -- FR-REG-001's "attempting to register twice
            # returns 409" acceptance criterion.
            models.UniqueConstraint(
                fields=["hackathon", "user"], name="unique_registration_per_hackathon_user",
            ),
        ]
        indexes = [
            models.Index(fields=["user"]),  # FR-REG-003 "my registrations" query
            models.Index(fields=["hackathon"]),
        ]

    @property
    def status(self):
        return "withdrawn" if self.withdrawn_at else "registered"

    def __str__(self):
        return f"{self.user_id} -> {self.hackathon_id} ({self.status})"