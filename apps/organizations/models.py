"""
organizations -- models

Implements FR modules: ORG
Depends on: accounts, core

Per Design Spec Sec 3.1: data shape and database-level constraints ONLY.
No business logic here -- see services.py.

Organization is a tenant ROOT (like accounts.Account), not a tenant-scoped
model, so it does not use TenantScopedManager -- see Design Spec Sec 3.3.
"""

import uuid

from django.db import models

from apps.core.models import TimeStampedModel

ORG_TYPE_CHOICES = [
    ("university", "University"),
    ("company", "Company"),
    ("ngo", "NGO"),
    ("government", "Government"),
]

VERIFICATION_STATUS_CHOICES = [
    ("unverified", "Unverified"),
    ("pending", "Pending"),
    ("verified", "Verified"),
]

REVIEW_DECISION_CHOICES = [
    ("approved", "Approved"),
    ("rejected", "Rejected"),
]


class Organization(TimeStampedModel):
    """Implements FR-ORG-001..003 (Design Spec Sec 3.2, DB Design Sec 4.2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=20, choices=ORG_TYPE_CHOICES)
    contact_email = models.EmailField()
    primary_email_domain = models.TextField(null=True, blank=True)  # FR-ORG-001: optional
    is_suspended = models.BooleanField(default=False)  # FR-ADMIN-001, set by apps.platform_admin

    verification_status = models.CharField(
        max_length=20, choices=VERIFICATION_STATUS_CHOICES, default="unverified"
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        "accounts.Account",
        on_delete=models.PROTECT,
        related_name="organizations_created",
    )  # the Organizer of record, per FR-ORG-001's implicit RoleAssignment

    class Meta:
        app_label = "organizations"
        indexes = [
            models.Index(fields=["primary_email_domain"]),  # FR-ORG-002 lookup
            models.Index(fields=["verification_status"]),  # FR-ORG-003 admin queue
            models.Index(fields=["is_suspended"]),  # FR-ADMIN-001 discovery filter
        ]

    def __str__(self):
        return self.name


class OrgVerificationDocument(TimeStampedModel):
    """Supporting evidence for FR-ORG-003 manual review.

    Max-3-per-organization is a service-layer constraint (DB Design Sec 4.2),
    not enforced here.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="verification_documents"
    )
    file_url = models.TextField()  # object storage pointer, Design Spec Sec 6.3
    uploaded_by = models.ForeignKey(
        "accounts.Account",
        on_delete=models.PROTECT,
        related_name="org_documents_uploaded",
    )

    class Meta:
        app_label = "organizations"
        indexes = [models.Index(fields=["organization"])]


class OrgVerificationReview(models.Model):
    """A Platform Admin's approve/reject decision for FR-ORG-003.

    rejection_reason-required-when-rejected is a service-layer check
    (DB Design Sec 4.2), not a DB CHECK constraint.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="verification_reviews"
    )
    reviewed_by = models.ForeignKey(
        "accounts.Account",
        on_delete=models.PROTECT,
        related_name="org_reviews_made",
    )  # must hold is_platform_admin; enforced in services.py
    decision = models.CharField(max_length=10, choices=REVIEW_DECISION_CHOICES)
    rejection_reason = models.TextField(null=True, blank=True)
    reviewed_at = models.DateTimeField(auto_now_add=True)  # feeds median-time-to-decision SLA

    class Meta:
        app_label = "organizations"
        indexes = [models.Index(fields=["organization"])]