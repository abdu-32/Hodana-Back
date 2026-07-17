"""
Django admin registrations for apps.organizations.

Same reasoning as apps/accounts/admin.py: not mandated by any doc, but
django.contrib.admin is installed project-wide -- these registrations
make Organization/verification records inspectable for support/ops
(e.g. manually checking why an org didn't auto-verify) without going
through the API.

Deliberately read-mostly: verification_status/verified_at are
service-layer-owned state (see services.py's _attempt_domain_verification
and review_organization_verification), so they're readonly here rather
than hand-editable -- an admin flipping the badge on directly would skip
the audit trail and the Organizer notification email that normally go
with a real decision.
"""

from django.contrib import admin

from .models import Organization, OrgVerificationDocument, OrgVerificationReview


class OrgVerificationDocumentInline(admin.TabularInline):
    model = OrgVerificationDocument
    extra = 0
    fields = ("file_url", "uploaded_by", "created_at")
    readonly_fields = ("file_url", "uploaded_by", "created_at")
    can_delete = False


class OrgVerificationReviewInline(admin.TabularInline):
    model = OrgVerificationReview
    extra = 0
    fields = ("decision", "reviewed_by", "rejection_reason", "reviewed_at")
    readonly_fields = ("decision", "reviewed_by", "rejection_reason", "reviewed_at")
    can_delete = False


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "type",
        "verification_status",
        "primary_email_domain",
        "created_by",
        "created_at",
    )
    list_filter = ("type", "verification_status")
    search_fields = ("id", "name", "contact_email", "primary_email_domain")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    autocomplete_fields = ("created_by",)
    inlines = [OrgVerificationDocumentInline, OrgVerificationReviewInline]

    # verification_status/verified_at change through services.py only
    # (domain auto-verify or a Platform Admin's review decision), each of
    # which also writes an AuditLogEntry and, for reviews, notifies the
    # Organizer -- editing them here would silently bypass both.
    readonly_fields = (
        "id",
        "verification_status",
        "verified_at",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (None, {"fields": ("id", "name", "type", "contact_email", "primary_email_domain")}),
        ("Verification", {"fields": ("verification_status", "verified_at")}),
        ("Ownership", {"fields": ("created_by",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(OrgVerificationDocument)
class OrgVerificationDocumentAdmin(admin.ModelAdmin):
    list_display = ("organization", "uploaded_by", "created_at")
    list_filter = ("organization__verification_status",)
    search_fields = ("organization__name", "uploaded_by__email", "file_url")
    autocomplete_fields = ("organization", "uploaded_by")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(OrgVerificationReview)
class OrgVerificationReviewAdmin(admin.ModelAdmin):
    list_display = ("organization", "decision", "reviewed_by", "reviewed_at")
    list_filter = ("decision",)
    search_fields = ("organization__name", "reviewed_by__email")
    autocomplete_fields = ("organization", "reviewed_by")
    readonly_fields = ("id", "reviewed_at")