"""
Root URLconf. Every Django app's own urls.py is included under
/api/v1/<app-name>/, mirroring the module boundaries in Design Spec Sec 3.2
so the API surface maps predictably to Document 04 (OpenAPI Specification).
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import TokenRefreshView

urlpatterns = [
    path("admin/", admin.site.urls),

    # Contract-first: this endpoint is introspected live from the actual
    # views/serializers below, then exported to contracts/openapi.yaml via
    # `scripts/export_contract.sh`. That exported file is the one thing the
    # frontend repo consumes — see innovation-hub-frontend/scripts/sync-contract.sh.
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/schema/swagger-ui/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),

    # Auth (login/refresh) — FR-AUTH, Design Spec Sec 4.1-4.2
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),

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
