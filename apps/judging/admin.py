"""
Django admin registrations for apps.judging.

The judging workflow is primarily managed through the API and services.py.
These registrations provide a read-mostly support/ops interface for
inspecting judging rounds, criteria, assignments, invitations, scores,
and materialized round results.

Stateful judging rules remain in services.py. Admin is not intended to
bypass those rules through manual edits.
"""

from django.contrib import admin

from .models import (
    JudgeInvitation,
    JudgingAssignment,
    JudgingCriterion,
    JudgingRound,
    RoundResult,
    Score,
)


@admin.register(JudgingRound)
class JudgingRoundAdmin(admin.ModelAdmin):
    list_display = (
        "hackathon",
        "track",
        "status",
        "opened_at",
        "closed_at",
    )
    list_filter = (
        "status",
    )
    search_fields = (
        "hackathon__name",
        "track__name",
    )
    autocomplete_fields = (
        "hackathon",
        "track",
    )
    ordering = (
        "hackathon",
        "track",
    )

    readonly_fields = (
        "id",
    )

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "hackathon",
                    "track",
                    "status",
                )
            },
        ),
        (
            "Timeline",
            {
                "fields": (
                    "opened_at",
                    "closed_at",
                )
            },
        ),
    )


@admin.register(JudgingCriterion)
class JudgingCriterionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "round",
        "min_score",
        "max_score",
        "weight",
    )
    list_filter = (
        "round__status",
    )
    search_fields = (
        "name",
        "round__hackathon__name",
    )
    autocomplete_fields = (
        "round",
    )
    ordering = (
        "round",
        "name",
    )

    readonly_fields = (
        "id",
    )


@admin.register(JudgingAssignment)
class JudgingAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "round",
        "submission",
        "judge_user",
        "assigned_at",
        "reassigned_from_user",
    )
    list_filter = (
        "round__status",
    )
    search_fields = (
        "judge_user__email",
        "judge_user__full_name",
        "submission__id",
        "round__hackathon__name",
    )
    autocomplete_fields = (
        "round",
        "submission",
        "judge_user",
        "reassigned_from_user",
    )
    ordering = (
        "-assigned_at",
    )

    readonly_fields = (
        "id",
        "assigned_at",
    )


@admin.register(JudgeInvitation)
class JudgeInvitationAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "round",
        "status",
        "invited_at",
        "responded_at",
    )
    list_filter = (
        "status",
        "round__status",
    )
    search_fields = (
        "email",
        "round__hackathon__name",
    )
    autocomplete_fields = (
        "round",
    )
    ordering = (
        "-invited_at",
    )

    readonly_fields = (
        "id",
        "invited_at",
        "responded_at",
    )


@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    list_display = (
        "submission",
        "judge_user",
        "criterion",
        "score_value",
        "status",
        "finalized_at",
        "created_at",
    )
    list_filter = (
        "status",
        "criterion__round__status",
    )
    search_fields = (
        "judge_user__email",
        "judge_user__full_name",
        "submission__id",
        "criterion__name",
    )
    autocomplete_fields = (
        "submission",
        "judge_user",
        "criterion",
    )
    ordering = (
        "-created_at",
    )

    # Finalized scores are part of the judging record and should not be
    # casually modified through the admin. Reopening/finalizing belongs
    # to the service layer.
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "finalized_at",
        "reopened_at",
    )


@admin.register(RoundResult)
class RoundResultAdmin(admin.ModelAdmin):
    list_display = (
        "round",
        "submission",
        "aggregate_score",
        "rank",
        "calculated_at",
    )
    list_filter = (
        "round__status",
    )
    search_fields = (
        "submission__id",
        "round__hackathon__name",
    )
    autocomplete_fields = (
        "round",
        "submission",
    )
    ordering = (
        "round",
        "rank",
    )

    # Results are materialized by the judging workflow. They should be
    # inspected here, not manually recalculated or edited.
    readonly_fields = (
        "id",
        "aggregate_score",
        "rank",
        "calculated_at",
    )