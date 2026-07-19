from django.contrib import admin

from .models import Submission, SubmissionVersion


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "id", "title", "hackathon", "team", "eligibility_status", "is_finalized", "submitted_at", "locked_at",
    )
    list_filter = ("eligibility_status", "is_finalized")
    search_fields = ("title", "team__team_name")


@admin.register(SubmissionVersion)
class SubmissionVersionAdmin(admin.ModelAdmin):
    list_display = ("id", "submission", "title", "edited_by", "created_at")
    search_fields = ("title",)