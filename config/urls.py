from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
# TokenRefreshView import removed -- accounts.views.RefreshView replaces it
# (contract shape + token_version check; see apps/accounts/services.py)

urlpatterns = [
    path("admin/", admin.site.urls),

    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),

    # Accounts app owns both Auth and Users (Doc 04) -- mounted at api/v1/
    # root, not api/v1/auth/, so its internal "auth/..." and "users/..."
    # prefixes resolve to api/v1/auth/... and api/v1/users/... correctly.
    path("api/v1/", include("apps.accounts.urls")),

    path("api/v1/organizations/", include("apps.organizations.urls")),
    path("api/v1/hackathons/", include("apps.hackathons.urls")),
    path("api/v1/registrations/", include("apps.registrations.urls")),
    path("api/v1/teams/", include("apps.teams.urls")),
    path("api/v1/submissions/", include("apps.submissions.urls")),
    path("api/v1/judging/", include("apps.judging.urls")),
    path("api/v1/showcase/", include("apps.showcase.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
    path("api/v1/analytics/", include("apps.analytics.urls")),
    path("api/v1/admin/", include("apps.platform_admin.urls")),
]