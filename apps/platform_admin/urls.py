"""
Mounted at api/v1/admin/ in config/urls.py, so every path below is
relative to that prefix.
"""

from django.urls import path

from apps.organizations import views as org_views
from . import views

app_name = "platform_admin"

urlpatterns = [
    # FR-ADMIN-001 -- organization verification dashboard (read side).
    path(
        "organizations/pending",
        views.PendingOrganizationsView.as_view(),
        name="organizations-pending",
    ),
    path(
        "organizations",
        views.AdminOrganizationsView.as_view(),
        name="organizations-list",
    ),
    path(
        "organizations/<uuid:id>/verification-review",
        org_views.OrganizationVerificationReviewView.as_view(),
        name="organization-verification-review",
    ),

    # Live platform management & telemetry
    path(
        "health",
        views.AdminHealthCheckView.as_view(),
        name="health",
    ),
    path(
        "hackathons",
        views.AdminHackathonsListView.as_view(),
        name="hackathons-list",
    ),
    path(
        "users",
        views.AdminUsersListView.as_view(),
        name="users-list",
    ),
    path(
        "metrics",
        views.AdminMetricsView.as_view(),
        name="metrics",
    ),
    path(
        "audit-logs",
        views.AdminAuditLogsView.as_view(),
        name="audit-logs",
    ),
    path(
        "financials",
        views.AdminFinancialsListView.as_view(),
        name="financials-list",
    ),
    path(
        "financials/<uuid:id>/release",
        views.AuthorizeEscrowReleaseView.as_view(),
        name="financials-release",
    ),
    path(
        "financials/<uuid:id>",
        views.DeleteFinancialRecordView.as_view(),
        name="financials-delete",
    ),

    # FR-ADMIN-001 -- suspend / reactivate a hackathon.
    path(
        "hackathons/<uuid:id>/suspend",
        views.SuspendHackathonView.as_view(),
        name="hackathon-suspend",
    ),
    path(
        "hackathons/<uuid:id>/reactivate",
        views.ReactivateHackathonView.as_view(),
        name="hackathon-reactivate",
    ),
    path(
        "hackathons/<uuid:id>/feature",
        views.ToggleHackathonFeaturedView.as_view(),
        name="hackathon-feature",
    ),

    # FR-ADMIN-001 -- suspend / reactivate an organization.
    path(
        "organizations/<uuid:id>/suspend",
        views.SuspendOrganizationView.as_view(),
        name="organization-suspend",
    ),
    path(
        "organizations/<uuid:id>/reactivate",
        views.ReactivateOrganizationView.as_view(),
        name="organization-reactivate",
    ),

    # FR-ADMIN-001 -- suspend / reactivate a user account.
    path(
        "users/<uuid:id>/suspend",
        views.SuspendAccountView.as_view(),
        name="user-suspend",
    ),
    path(
        "users/<uuid:id>/reactivate",
        views.ReactivateAccountView.as_view(),
        name="user-reactivate",
    ),
    path(
        "users/<uuid:id>",
        views.DeleteAccountView.as_view(),
        name="user-detail",
    ),
    path(
        "users/<uuid:id>/delete",
        views.DeleteAccountView.as_view(),
        name="user-delete",
    ),

    # FR-ADMIN-002 -- platform-wide search.
    path(
        "search",
        views.PlatformSearchView.as_view(),
        name="search",
    ),
]
