"""
Django admin registrations for apps.accounts.

Not mandated by any doc (Doc 03/08 never mention the built-in admin site),
but django.contrib.admin is installed and admin/ is wired up in
config/urls.py with nothing registered anywhere in the project -- these
registrations make Account/Badge/RoleAssignment inspectable for
support/ops without going through the API.

Deliberately NOT a full auth.UserAdmin clone (no password-change form,
no add-user wizard): this is a read-mostly support tool, not the primary
way accounts get created (that's FR-AUTH-001 via the API).
"""

from django.contrib import admin

from .models import Account, Badge, RoleAssignment


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = (
        "email",
        "full_name",
        "verification_status",
        "is_suspended",
        "is_platform_admin",
        "last_login_at",
        "created_at",
    )
    list_filter = (
        "verification_status",
        "is_suspended",
        "is_platform_admin",
        "profile_visibility",
        "oauth_provider",
    )
    search_fields = ("id", "email", "full_name")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    # `password` is the hash -- editable-by-default here would let someone
    # accidentally overwrite it with plaintext and lock the account out of
    # auth entirely; token_version/failed_login_count/lock_until are
    # security-state fields services.py owns, not something to hand-edit.
    readonly_fields = (
        "id",
        "password",
        "token_version",
        "failed_login_count",
        "lock_until",
        "email_verified_at",
        "last_login_at",
        "created_at",
        "updated_at",
    )

    fieldsets = (
        (None, {"fields": ("id", "email", "password", "full_name")}),
        ("Profile", {"fields": ("bio", "university", "skills", "avatar_url", "portfolio_url", "profile_visibility", "contact_email")}),
        ("Status", {"fields": ("verification_status", "email_verified_at", "is_suspended", "is_platform_admin", "is_staff", "deleted_at")}),
        ("Security", {"fields": ("token_version", "failed_login_count", "lock_until", "last_login_at")}),
        ("OAuth", {"fields": ("oauth_provider", "oauth_subject")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ("user", "type", "awarded_at")
    list_filter = ("type",)
    search_fields = ("user__email", "user__full_name")
    autocomplete_fields = ("user",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "scope_type", "scope_id", "created_at")
    list_filter = ("role", "scope_type")
    search_fields = ("user__email", "user__full_name", "scope_id")
    autocomplete_fields = ("user",)
    readonly_fields = ("id", "created_at")