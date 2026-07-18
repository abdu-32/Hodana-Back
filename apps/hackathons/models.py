"""
hackathons -- models

Implements FR modules: HACK, DISC, TRACK
Depends on: organizations

Per Design Spec Sec 3.1: data shape and database-level constraints ONLY.
No business logic here -- see services.py.

Hackathon is the tenant-scope anchor per Design Spec Sec 3.3 (scoped by
host_org); ChallengeTrack is scoped by hackathon. Both declare a
TenantScopedManager scope_field per that section.

ELIG (FR-ELIG-001/002) is NOT implemented here: it operates on `locked`
submissions (FR-SUB-003 precondition), and apps.submissions is still an
unimplemented stub with no Submission model to reference. Revisit once
that app exists.
"""

import uuid

from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.core.managers import TenantScopedManager
from apps.core.models import TimeStampedModel

LOCATION_MODE_CHOICES = [
    ("online", "Online"),
    ("in_person", "In Person"),
    ("hybrid", "Hybrid"),
]

HACKATHON_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("published", "Published"),
    ("archived", "Archived"),
]


class HackathonManager(TenantScopedManager):
    scope_field = "host_org"


class Hackathon(TimeStampedModel):
    """Implements FR-HACK-001..005, FR-DISC-001..003 (DB Design Sec 4.3).

    Doc 02's FR-HACK-001 required-fields list mentions a standalone
    "start date, end date" pair that DB Design Sec 4.3 doesn't define as
    columns -- only registration_opens/closes_at and
    submission_opens/closes_at exist there. Treating submission_opens_at /
    submission_closes_at as the event's start/end (the actual hacking
    period) since that's the closest real column pair; flagging the
    SRS/DB-Design mismatch here rather than inventing new columns DB
    Design doesn't call for.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    host_org = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="hackathons",
    )  # tenant-scoping column, Design Spec Sec 3.3

    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)  # FR-DISC-003 public URL segment
    description = models.TextField(blank=True)
    banner_url = models.TextField(blank=True)

    registration_opens_at = models.DateTimeField()
    registration_closes_at = models.DateTimeField()
    submission_opens_at = models.DateTimeField()
    submission_closes_at = models.DateTimeField()

    rules = models.TextField(blank=True)
    prize_info = models.TextField(blank=True)
    location_mode = models.CharField(max_length=20, choices=LOCATION_MODE_CHOICES, default="online")

    # FR-HACK-003; structure/required-non-null-before-publish (BR-004)
    # validated in services.py, not here (Design Spec Sec 3.1).
    eligibility_rules = models.JSONField(null=True, blank=True)
    tags = ArrayField(models.TextField(), default=list, blank=True)

    status = models.CharField(max_length=20, choices=HACKATHON_STATUS_CHOICES, default="draft")
    showcase_published_at = models.DateTimeField(null=True, blank=True)  # gates FR-SHOWCASE-001 visibility

    created_by = models.ForeignKey(
        "accounts.Account", on_delete=models.PROTECT, related_name="hackathons_created",
    )

    objects = HackathonManager()

    class Meta:
        app_label = "hackathons"
        constraints = [
            # Schema-level halves of BR-002/BR-003; the "closes in the
            # past" / "on or after registration close" halves are
            # service-layer checks against now(), per DB Design Sec 4.3's
            # own note that those are evaluated per-request, not per-write.
            models.CheckConstraint(
                condition=models.Q(registration_closes_at__gt=models.F("registration_opens_at")),
                name="hackathon_registration_close_after_open",
            ),
            models.CheckConstraint(
                condition=models.Q(submission_closes_at__gt=models.F("submission_opens_at")),
                name="hackathon_submission_close_after_open",
            ),
        ]
        indexes = [
            # FR-DISC-001 published-catalog query.
            models.Index(fields=["status", "registration_opens_at"], name="hackathon_status_regopen_idx"),
            # FR-DISC-002 tag filtering.
            GinIndex(fields=["tags"], name="hackathon_tags_gin_idx"),
        ]
        # NOTE: DB Design Sec 4.3 also calls for a pg_trgm GIN trigram
        # index on `title` for NFR-PERF-002's sub-1-second keyword search
        # at 5,000-hackathon scale. Not added here: it requires the
        # pg_trgm extension (CREATE EXTENSION pg_trgm via a
        # TrigramExtension migration operation), which nothing in this
        # codebase has set up yet. list_hackathons() below uses a plain
        # icontains search in the meantime -- fine at MVP volumes, revisit
        # before the 5,000-hackathon target matters.

    def __str__(self):
        return self.title


class ChallengeTrackManager(TenantScopedManager):
    scope_field = "hackathon"


class ChallengeTrack(models.Model):
    """Implements FR-TRACK-001, FR-TRACK-002 (DB Design Sec 4.3).

    DB Design's `challenge_track` table only has `created_at` (no
    `updated_at`), so this doesn't use TimeStampedModel -- same pattern as
    organizations.OrgVerificationReview.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hackathon = models.ForeignKey(Hackathon, on_delete=models.CASCADE, related_name="tracks")
    sponsor_org = models.ForeignKey(
        "organizations.Organization", on_delete=models.PROTECT, related_name="sponsored_tracks",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    prize = models.TextField(blank=True)
    rubric_reference = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ChallengeTrackManager()

    class Meta:
        app_label = "hackathons"
        constraints = [
            # FR-TRACK-001: "distinct name within the hackathon".
            models.UniqueConstraint(fields=["hackathon", "name"], name="unique_track_name_per_hackathon"),
        ]
        indexes = [
            models.Index(fields=["hackathon"]),
            models.Index(fields=["sponsor_org"]),  # BR-009's Sponsor-scoped access check
        ]

    def __str__(self):
        return f"{self.name} ({self.hackathon.title})"