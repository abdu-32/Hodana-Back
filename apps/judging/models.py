"""
judging -- models

Implements FR-HACK-004 and FR-JUDGE-001..004.

Per Design Spec Sec 3.1: models contain data shape and database-level
constraints only. Stateful rules live in services.py.
"""

import uuid

from django.db import models

from apps.core.models import TimeStampedModel


ROUND_STATUS_CHOICES = [
    ("not_started", "Not Started"),
    ("open", "Open"),
    ("closed", "Closed"),
]

INVITATION_STATUS_CHOICES = [
    ("sent", "Sent"),
    ("accepted", "Accepted"),
    ("declined", "Declined"),
    ("revoked", "Revoked"),
    ("expired", "Expired"),
]

SCORE_STATUS_CHOICES = [
    ("draft", "Draft"),
    ("final", "Final"),
]


class JudgingRound(models.Model):
    """FR-JUDGE-004. track=None is the Overall round."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hackathon = models.ForeignKey(
        "hackathons.Hackathon",
        on_delete=models.CASCADE,
        related_name="judging_rounds",
    )
    track = models.ForeignKey(
        "hackathons.ChallengeTrack",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="judging_rounds",
    )
    status = models.CharField(
        max_length=20, choices=ROUND_STATUS_CHOICES, default="not_started",
    )
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "judging"
        constraints = [
            models.UniqueConstraint(
                fields=["hackathon", "track"],
                name="unique_judging_round_per_hackathon_track",
            ),
            models.UniqueConstraint(
                fields=["hackathon"],
                condition=models.Q(track__isnull=True),
                name="unique_overall_judging_round_per_hackathon",
            ),
        ]
        indexes = [
            models.Index(fields=["hackathon"]),
        ]

    def __str__(self):
        return f"{self.hackathon_id} / {self.track_id or 'overall'}"


class JudgingCriterion(models.Model):
    """FR-HACK-004 / BR-005."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    round = models.ForeignKey(
        JudgingRound, on_delete=models.CASCADE, related_name="criteria",
    )
    name = models.CharField(max_length=100)
    min_score = models.IntegerField()
    max_score = models.IntegerField()
    weight = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        app_label = "judging"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(max_score__gt=models.F("min_score")),
                name="criterion_max_gt_min",
            ),
            models.CheckConstraint(
                condition=models.Q(weight__gte=0, weight__lte=100),
                name="criterion_weight_0_to_100",
            ),
        ]
        indexes = [models.Index(fields=["round"])]

    def __str__(self):
        return self.name


class JudgingAssignment(models.Model):
    """FR-JUDGE-001."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    round = models.ForeignKey(
        JudgingRound, on_delete=models.CASCADE, related_name="assignments",
    )
    submission = models.ForeignKey(
        "submissions.Submission",
        on_delete=models.CASCADE,
        related_name="judging_assignments",
    )
    judge_user = models.ForeignKey(
        "accounts.Account",
        on_delete=models.CASCADE,
        related_name="judging_assignments",
    )
    assigned_at = models.DateTimeField()
    reassigned_from_user = models.ForeignKey(
        "accounts.Account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reassigned_judging_assignments",
    )

    class Meta:
        app_label = "judging"
        constraints = [
            models.UniqueConstraint(
                fields=["round", "submission", "judge_user"],
                name="unique_round_submission_judge_assignment",
            ),
        ]
        indexes = [
            models.Index(fields=["judge_user"]),
        ]


class JudgeInvitation(models.Model):
    """The judge onboarding path underlying FR-JUDGE-001."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    round = models.ForeignKey(
        JudgingRound, on_delete=models.CASCADE, related_name="invitations",
    )
    status = models.CharField(
        max_length=10, choices=INVITATION_STATUS_CHOICES, default="sent",
    )
    invited_at = models.DateTimeField()
    responded_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        app_label = "judging"
        indexes = [
            models.Index(fields=["round"]),
            models.Index(fields=["email"]),
        ]


class Score(TimeStampedModel):
    """FR-JUDGE-002.

    The design DB table omitted a status column even though the SRS explicitly
    requires draft/final scoring and immutable final scores. This implementation
    adds status as the minimum schema needed to make that requirement enforceable.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submission = models.ForeignKey(
        "submissions.Submission", on_delete=models.CASCADE, related_name="scores",
    )
    judge_user = models.ForeignKey(
        "accounts.Account", on_delete=models.CASCADE, related_name="scores_given",
    )
    criterion = models.ForeignKey(
        JudgingCriterion, on_delete=models.CASCADE, related_name="scores",
    )
    score_value = models.IntegerField()
    comment = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=10, choices=SCORE_STATUS_CHOICES, default="final",
    )
    finalized_at = models.DateTimeField(null=True, blank=True)
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopen_reason = models.TextField(blank=True, default="")

    class Meta:
        app_label = "judging"
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "judge_user", "criterion"],
                name="unique_score_per_submission_judge_criterion",
            ),
        ]
        indexes = [
            models.Index(fields=["submission", "judge_user"]),
        ]


class RoundResult(models.Model):
    """FR-JUDGE-003. One materialized result per round/submission."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    round = models.ForeignKey(
        JudgingRound, on_delete=models.CASCADE, related_name="results",
    )
    submission = models.ForeignKey(
        "submissions.Submission", on_delete=models.CASCADE, related_name="round_results",
    )
    aggregate_score = models.DecimalField(max_digits=6, decimal_places=2)
    rank = models.PositiveSmallIntegerField(null=True, blank=True)
    calculated_at = models.DateTimeField()

    class Meta:
        app_label = "judging"
        constraints = [
            models.UniqueConstraint(
                fields=["round", "submission"],
                name="unique_round_result_per_submission",
            ),
        ]
        indexes = [
            models.Index(fields=["round", "rank"]),
        ]
