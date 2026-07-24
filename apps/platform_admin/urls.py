"""
Mounted at api/v1/admin/ in config/urls.py, so every path below is
relative to that prefix.
"""

from django.urls import path

from . import views

app_name = "platform_admin"

urlpatterns = [
    # FR-ADMIN-001 -- organization verification dashboard (read side).
    path(
        "organizations/pending",
        views.PendingOrganizationsView.as_view(),
        name="organizations-pending",
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

    # FR-ADMIN-002 -- platform-wide search.
    path(
        "search",
        views.PlatformSearchView.as_view(),
        name="search",
    ),
]
