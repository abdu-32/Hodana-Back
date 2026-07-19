"""
submissions -- models

Implements FR modules: SUB
Depends on: teams

Per Design Spec Sec 3.1: data shape and database-level constraints ONLY.
No business logic here -- see services.py.

Per Design Spec Sec 3.3: every tenant-scoped model must use
TenantScopedManager from apps.core and declare its scoping field.

DB Design Sec 4.6's `submission` table has `repo_link TEXT NOT NULL`, while
SRS FR-SUB-001's acceptance criterion only requires "at least one of
{repository URL, demo URL, uploaded media}" -- and FR-SUB-003 makes clear
that full requiredness (title, description, at-least-one-of-the-three) is
a *finalize*-time gate, not a draft-save-time one (its precondition is
literally "the submission has all required fields (FR-SUB-001)", implying
a draft may not yet). Reconciled here the same way DB Design's own
`repo_link` NOT NULL sits next to an optional value elsewhere: the column
is NOT NULL but not non-blank, defaulting to "" so an incomplete draft can
still be persisted; services.py enforces the real "must have title +
description + at least one of {repo, demo, media}" rule at finalize time.

`SubmissionVersion` (FR-SUB-004) is NOT in DB Design Sec 4.6 -- that
document only defines `submission` and `submission_track`. Added here as
the concrete table needed to satisfy FR-SUB-004's "retain up to the 10
most recent versions" requirement; trimming to 10 is enforced in
services.py, not the DB.
"""

import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.managers import TenantScopedManager

ELIGIBILITY_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("eligible", "Eligible"),
    ("disqualified", "Disqualified"),
]


class SubmissionManager(TenantScopedManager):
    scope_field = "hackathon"


class Submission(models.Model):
    """Implements FR-SUB-001 through FR-SUB-003 (DB Design Sec 4.6).

    FR-ELIG-001/002 (screening) reads/writes `eligibility_status` and its
    companion columns, but that business logic lives in apps.hackathons
    per Design Spec Sec 3.2's module-to-app mapping -- this model only
    carries the schema those columns require.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hackathon = models.ForeignKey(
        "hackathons.Hackathon", on_delete=models.CASCADE, related_name="submissions",
    )  # tenant-scoping column, Design Spec Sec 3.3
    team = models.OneToOneField(
        "teams.Team", on_delete=models.CASCADE, related_name="submission",
    )  # UNIQUE per DB Design Sec 4.6: one submission per team

    title = models.CharField(max_length=255, blank=True, default="")
    tagline = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")  # FR-SUB-001: <= 3,000 chars, enforced in serializers.py
    technologies = ArrayField(models.TextField(), default=list, blank=True)  # DB Design Sec 4.6: TEXT[]

    # See module docstring re: NOT NULL vs required-at-finalize-only.
    repo_link = models.TextField(blank=True, default="")
    demo_video_url = models.TextField(blank=True, default="")
    # DB Design Sec 4.6: "pointers into object storage per direct-upload
    # design (ADR-005)" -- the client uploads media directly to storage
    # and hands back URLs; this app only tracks the pointers.
    attachment_urls = ArrayField(models.TextField(), default=list, blank=True)  # FR-SUB-002: max 5, enforced in services.py

    eligibility_status = models.CharField(
        max_length=20, choices=ELIGIBILITY_STATUS_CHOICES, default="eligible",
    )  # BR-006: defaults to eligible, not pending
    eligibility_reason = models.TextField(blank=True, default="")
    eligibility_reviewed_by = models.ForeignKey(
        "accounts.Account", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="submissions_reviewed",
    )
    eligibility_reviewed_at = models.DateTimeField(null=True, blank=True)

    is_finalized = models.BooleanField(default=False)  # FR-SUB-003
    submitted_at = models.DateTimeField(null=True, blank=True)  # first-save timestamp
    locked_at = models.DateTimeField(null=True, blank=True)  # set once the deadline passes; BR-003

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = SubmissionManager()

    class Meta:
        app_label = "submissions"
        indexes = [
            # FR-ELIG-002's bulk screening view, per DB Design Sec 4.6.
            models.Index(fields=["hackathon", "eligibility_status"]),
        ]

    def __str__(self):
        return f"{self.title or '(untitled)'} ({self.team_id})"


class SubmissionVersion(models.Model):
    """Implements FR-SUB-004. Not in DB Design Sec 4.6 -- see module
    docstring. A snapshot is written each time a save changes the
    description, so the team can review how their pitch evolved; never
    exposed to judges or the public (FR-SUB-004 acceptance criterion)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="versions")
    title = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True, default="")
    edited_by = models.ForeignKey(
        "accounts.Account", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="submission_versions_edited",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "submissions"
        indexes = [
            models.Index(fields=["submission", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.submission_id} @ {self.created_at:%Y-%m-%d %H:%M}"