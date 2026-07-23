"""
Django admin registration for apps.showcase.

Visibility overrides are an audited Organizer action (FR-SHOWCASE-001);
this registration is a read-mostly support/ops view onto that log, not a
substitute for going through the API (services.set_submission_visibility).
"""

from django.contrib import admin

from .models import ShowcaseOverride


@admin.register(ShowcaseOverride)
class ShowcaseOverrideAdmin(admin.ModelAdmin):
    list_display = (
        "submission",
        "hackathon",
        "is_visible",
        "created_by",
        "created_at",
    )
    list_filter = (
        "is_visible",
    )
    search_fields = (
        "submission__id",
        "submission__title",
        "hackathon__title",
        "created_by__email",
    )
    autocomplete_fields = (
        "hackathon",
        "submission",
        "created_by",
    )
    ordering = (
        "-created_at",
    )

    # The reason is a logged justification for an already-made decision;
    # edit it by creating a fresh override through the API, not in place.
    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
    )