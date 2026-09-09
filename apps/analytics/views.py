"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).

Access control itself (Organizer of this specific hackathon, or a
Platform Admin) is enforced in services._require_analytics_access, per
the same "server-side, on every state-changing endpoint... independent
of any client-provided role claim" pattern as every other module (Design
Spec Sec 4.3) -- these views only require the request to be
authenticated at all.
"""

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import serializers, services


class PlatformStatsView(APIView):
    """GET /analytics/platform-stats -- Public ecosystem totals and active developer count."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: serializers.PlatformStatsSerializer})
    def get(self, request):
        stats = services.get_platform_stats()
        return Response(serializers.PlatformStatsSerializer(stats).data)


class RegistrationDashboardView(APIView):
    """GET /analytics/hackathons/{hackathon_id}/dashboard -- FR-ANALYTICS-001.
    Registration count over time, team formation rate, and submission
    conversion rate for one hackathon; restricted to that hackathon's
    Organizer and to Platform Admins (services.get_registration_dashboard)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.RegistrationDashboardSerializer})
    def get(self, request, hackathon_id):
        dashboard = services.get_registration_dashboard(
            actor=request.user, hackathon_id=hackathon_id,
        )
        return Response(serializers.RegistrationDashboardSerializer(dashboard).data)


class DemographicBreakdownView(APIView):
    """GET /analytics/hackathons/{hackathon_id}/demographics -- FR-ANALYTICS-002.
    Aggregated, anonymized breakdown of registrants by university and
    self-reported skill category; restricted the same way as the
    dashboard above. Returns `available: false` with a placeholder,
    rather than a 4xx, when the hackathon hasn't cleared BR-011's
    10-registration cohort floor (services.get_demographic_breakdown)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.DemographicBreakdownSerializer})
    def get(self, request, hackathon_id):
        breakdown = services.get_demographic_breakdown(
            actor=request.user, hackathon_id=hackathon_id,
        )
        return Response(serializers.DemographicBreakdownSerializer(breakdown).data)
