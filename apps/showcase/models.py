"""
showcase -- models

Implements FR modules: SHOWCASE
Depends on: judging, accounts

Per Design Spec Sec 3.1: data shape and database-level constraints ONLY.
No business logic here -- see services.py.

Per Design Spec Sec 3.3: every tenant-scoped model must use
TenantScopedManager from apps.core and declare its scoping field.

Document 05 does not define a table for this app -- FR-SHOWCASE-001/002
are read-only projections over `hackathon.showcase_published_at`
(hackathons app) and `round_result` (judging app), which is why nothing
here duplicates submission/result data. The one thing Doc 05 has no home
for at all is FR-SHOWCASE-001's "Organizer may override visibility per
submission with a logged reason" acceptance criterion -- disqualified-but-
still-shown, or eligible-but-hidden, is a decision with an audit trail
that has to live *somewhere*, and `submission.eligibility_status` (owned
by apps.submissions) is the wrong place for it: that column means "did
FR-ELIG-001 screening pass", not "does the Organizer want this shown on
the public page". ShowcaseOverride below is the minimum concrete table
needed to make that acceptance criterion enforceable, same reasoning as
submissions.SubmissionVersion adding a table Doc 05 doesn't define.
"""

import uuid

from django.db import models

from apps.core.managers import TenantScopedManager
from apps.core.models import TimeStampedModel


class ShowcaseOverrideManager(TenantScopedManager):
    scope_field = "hackathon"


class ShowcaseOverride(TimeStampedModel):
    """A logged Organizer decision to show or hide one submission on the
    public showcase, overriding the default derived from
    `submission.eligibility_status` (BR-006/BR-007: eligible submissions
    show by default, disqualified ones hide by default).

    `hackathon` is denormalized from `submission.hackathon` at write time
    purely so this model can declare a TenantScopedManager scope_field
    per Design Spec Sec 3.3 -- the same "so BR-style guarantees are a
    database-level fact, not just a service-layer check" trade-off
    `teams.TeamMember` makes for its own denormalized `hackathon` FK.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hackathon = models.ForeignKey(
        "hackathons.Hackathon", on_delete=models.CASCADE, related_name="showcase_overrides",
    )  # tenant-scoping column, Design Spec Sec 3.3
    submission = models.OneToOneField(
        "submissions.Submission", on_delete=models.CASCADE, related_name="showcase_override",
    )
    is_visible = models.BooleanField()
    reason = models.TextField()
    created_by = models.ForeignKey(
        "accounts.Account", on_delete=models.PROTECT, related_name="showcase_overrides_made",
    )

    objects = ShowcaseOverrideManager()

    class Meta:
        app_label = "showcase"
        indexes = [
            models.Index(fields=["hackathon"]),
        ]

    def __str__(self):
        return f"{self.submission_id} -> {'visible' if self.is_visible else 'hidden'}"