"""
teams -- models

Implements FR modules: TEAM
Depends on: hackathons, accounts, registrations

Per Design Spec Sec 3.1: data shape and database-level constraints ONLY.
No business logic here -- see services.py.

DB Design Sec 4.5's `team` table only has `created_at` (no `updated_at`),
so this doesn't use TimeStampedModel -- same pattern as
registrations.Registration / hackathons.ChallengeTrack.

`team_member` has no `role` column: "Owner" vs "Member" is derived from
whether a row's `user_id` matches `team.leader_user_id`, not stored
redundantly (DB Design Sec 4.5).
"""

import uuid

from django.db import models

from apps.core.managers import TenantScopedManager

JOIN_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("accepted", "Accepted"),
    ("declined", "Declined"),
]


class TeamManager(TenantScopedManager):
    scope_field = "hackathon"


class Team(models.Model):
    """Implements FR-TEAM-001, FR-TEAM-005 (DB Design Sec 4.5)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    hackathon = models.ForeignKey(
        "hackathons.Hackathon", on_delete=models.CASCADE, related_name="teams",
    )  # tenant-scoping column, Design Spec Sec 3.3
    team_name = models.CharField(max_length=60)
    description = models.TextField(blank=True, default="")
    leader_user = models.ForeignKey(
        "accounts.Account", on_delete=models.CASCADE, related_name="teams_led",
    )
    open_to_members = models.BooleanField(default=True)
    # Snapshot of hackathon.eligibility_rules["max_team_size"] taken at
    # creation time (services.create_team), not a live reference to the
    # hackathon -- FR-HACK-003's own acceptance criterion says rule
    # changes don't retroactively apply to things already created under
    # the old rules, same reasoning as registrations not being
    # retroactively invalidated.
    max_size = models.SmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = TeamManager()

    class Meta:
        app_label = "teams"
        constraints = [
            # FR-TEAM-001: "Team name is required ... unique within the
            # hackathon."
            models.UniqueConstraint(
                fields=["hackathon", "team_name"], name="unique_team_name_per_hackathon",
            ),
            models.CheckConstraint(condition=models.Q(max_size__gt=0), name="team_max_size_positive"),
        ]
        indexes = [
            models.Index(fields=["hackathon"]),
        ]

    def __str__(self):
        return f"{self.team_name} ({self.hackathon_id})"


class TeamMemberManager(TenantScopedManager):
    scope_field = "hackathon"


class TeamMember(models.Model):
    """Implements FR-TEAM-002 through FR-TEAM-004; the same row models
    both a pending invitation and an accepted membership (DB Design
    Sec 4.5)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="members")
    # Denormalized from team.hackathon_id at write time -- the deliberate
    # trade-off documented in DB Design Sec 4.5 to make BR-001 ("a
    # participant may belong to only one team per hackathon") a
    # database-level unique-index guarantee rather than a
    # service-layer-only check, consistent with the TenantScopedManager
    # precedent (Design Spec Sec 3.3).
    hackathon = models.ForeignKey(
        "hackathons.Hackathon", on_delete=models.CASCADE, related_name="team_memberships",
    )
    user = models.ForeignKey(
        "accounts.Account", on_delete=models.CASCADE, related_name="team_memberships",
        null=True, blank=True,
    )
    invitee_email = models.EmailField()
    join_status = models.CharField(max_length=10, choices=JOIN_STATUS_CHOICES, default="pending")
    invited_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()  # invited_at + 7 days, set in services.py per FR-TEAM-002
    responded_at = models.DateTimeField(null=True, blank=True)

    objects = TeamMemberManager()

    class Meta:
        app_label = "teams"
        constraints = [
            # BR-001, scoped per hackathon (not per team) -- see module
            # docstring. A user may hold at most one *accepted* row per
            # hackathon; multiple declined/pending rows are fine.
            models.UniqueConstraint(
                fields=["hackathon", "user"],
                condition=models.Q(join_status="accepted"),
                name="unique_accepted_membership_per_hackathon_user",
            ),
        ]
        indexes = [
            models.Index(fields=["team"]),
        ]

    @property
    def role(self):
        """Derived, never stored -- see module docstring."""
        if self.join_status != "accepted":
            return None
        return "owner" if self.user_id == self.team.leader_user_id else "member"

    def __str__(self):
        return f"{self.user_id} -> {self.team_id} ({self.join_status})"


JOIN_REQUEST_STATUS_CHOICES = [
    ("pending", "Pending"),
    ("accepted", "Accepted"),
    ("rejected", "Rejected"),
    ("cancelled", "Cancelled"),
]


class TeamJoinRequestManager(TenantScopedManager):
    scope_field = "hackathon"


class TeamJoinRequest(models.Model):
    """Models a participant requesting to join an open team in a hackathon."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="join_requests")
    hackathon = models.ForeignKey(
        "hackathons.Hackathon", on_delete=models.CASCADE, related_name="team_join_requests",
    )
    user = models.ForeignKey(
        "accounts.Account", on_delete=models.CASCADE, related_name="team_join_requests",
    )
    message = models.TextField(blank=True, default="")
    status = models.CharField(max_length=15, choices=JOIN_REQUEST_STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    objects = TeamJoinRequestManager()

    class Meta:
        app_label = "teams"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user"],
                condition=models.Q(status="pending"),
                name="unique_pending_join_request_per_team_user",
            ),
        ]
        indexes = [
            models.Index(fields=["hackathon"]),
            models.Index(fields=["user"]),
        ]

    def __str__(self):
        return f"{self.user_id} -> join request to {self.team_id} ({self.status})"