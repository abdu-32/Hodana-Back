"""
Django admin registrations for apps.hackathons. Same reasoning as
apps/organizations/admin.py: not mandated by any doc, but makes hackathons
and tracks inspectable for support/ops without going through the API.
"""

from django.contrib import admin

from .models import ChallengeTrack, Hackathon


class ChallengeTrackInline(admin.TabularInline):
    model = ChallengeTrack
    extra = 0
    fields = ("name", "sponsor_org", "prize", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Hackathon)
class HackathonAdmin(admin.ModelAdmin):
    list_display = ("title", "host_org", "status", "is_suspended", "location_mode", "registration_closes_at", "created_at")
    list_filter = ("status", "is_suspended", "location_mode")
    search_fields = ("id", "title", "slug", "host_org__name")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("host_org", "created_by")
    readonly_fields = ("id", "is_suspended", "created_at", "updated_at")
    inlines = [ChallengeTrackInline]
    fieldsets = (
        (None, {"fields": ("id", "title", "slug", "description", "banner_url", "host_org")}),
        ("Timeline", {"fields": (
            "registration_opens_at", "registration_closes_at",
            "submission_opens_at", "submission_closes_at",
        )}),
        ("Configuration", {"fields": ("location_mode", "rules", "prize_info", "eligibility_rules", "tags")}),
        ("Lifecycle", {"fields": ("status", "showcase_published_at")}),
        ("Moderation", {"fields": ("is_suspended",)}),
        ("Ownership", {"fields": ("created_by",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(ChallengeTrack)
class ChallengeTrackAdmin(admin.ModelAdmin):
    list_display = ("name", "hackathon", "sponsor_org", "created_at")
    search_fields = ("name", "hackathon__title", "sponsor_org__name")
    autocomplete_fields = ("hackathon", "sponsor_org")
    readonly_fields = ("id", "created_at")