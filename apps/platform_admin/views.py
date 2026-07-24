"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).

Every view below is restricted to IsPlatformAdmin (core.permissions) --
FR-ADMIN-001/002's shared precondition: "the requester holds the global
Platform Admin role" -- so a non-admin gets HTTP 403 uniformly across the
whole module, matching FR-ADMIN-001's acceptance criterion. services.py
re-checks the same thing for defense-in-depth (see that module's
docstring), same pattern already used by
organizations.OrganizationVerificationReviewView.
"""

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsPlatformAdmin

from . import serializers, services

# --------------------------------------------------------------------------
# FR-ADMIN-001: organization verification dashboard (read side)
# --------------------------------------------------------------------------


class PendingOrganizationsView(APIView):
    """GET /admin/organizations/pending -- FR-ADMIN-001's "dashboard to
    review pending organization verifications". The decision action
    itself is organizations.OrganizationVerificationReviewView (POST
    /organizations/{id}/verification-review) -- see that view's and
    services.list_pending_organizations's docstrings for why it lives
    there and not here."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: serializers.AdminOrganizationSerializer(many=True)})
    def get(self, request):
        organizations = services.list_pending_organizations(admin=request.user)
        body = serializers.AdminOrganizationSerializer(organizations, many=True).data
        return Response(body)


# --------------------------------------------------------------------------
# FR-ADMIN-001: suspend / reactivate a hackathon
# --------------------------------------------------------------------------


class SuspendHackathonView(APIView):
    """POST /admin/hackathons/{id}/suspend -- FR-ADMIN-001."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ModerationActionSerializer,
        responses={200: serializers.AdminHackathonSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hackathon = services.suspend_hackathon(
            admin=request.user, hackathon_id=id, reason=serializer.validated_data["reason"],
        )
        return Response(serializers.AdminHackathonSerializer(hackathon).data)


class ReactivateHackathonView(APIView):
    """POST /admin/hackathons/{id}/reactivate. Not called for by an
    explicit FR-ADMIN-001 acceptance criterion -- see
    services.reactivate_hackathon's docstring for why it exists anyway."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ModerationActionSerializer,
        responses={200: serializers.AdminHackathonSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hackathon = services.reactivate_hackathon(
            admin=request.user, hackathon_id=id, reason=serializer.validated_data["reason"],
        )
        return Response(serializers.AdminHackathonSerializer(hackathon).data)


# --------------------------------------------------------------------------
# FR-ADMIN-001: suspend / reactivate an organization
# --------------------------------------------------------------------------


class SuspendOrganizationView(APIView):
    """POST /admin/organizations/{id}/suspend -- FR-ADMIN-001."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ModerationActionSerializer,
        responses={200: serializers.AdminOrganizationSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization = services.suspend_organization(
            admin=request.user, organization_id=id, reason=serializer.validated_data["reason"],
        )
        return Response(serializers.AdminOrganizationSerializer(organization).data)


class ReactivateOrganizationView(APIView):
    """POST /admin/organizations/{id}/reactivate."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ModerationActionSerializer,
        responses={200: serializers.AdminOrganizationSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization = services.reactivate_organization(
            admin=request.user, organization_id=id, reason=serializer.validated_data["reason"],
        )
        return Response(serializers.AdminOrganizationSerializer(organization).data)


# --------------------------------------------------------------------------
# FR-ADMIN-001: suspend / reactivate a user account
# --------------------------------------------------------------------------


class SuspendAccountView(APIView):
    """POST /admin/users/{id}/suspend -- FR-ADMIN-001."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ModerationActionSerializer,
        responses={200: serializers.AdminAccountSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = services.suspend_account(
            admin=request.user, user_id=id, reason=serializer.validated_data["reason"],
        )
        return Response(serializers.AdminAccountSerializer(account).data)


class ReactivateAccountView(APIView):
    """POST /admin/users/{id}/reactivate."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ModerationActionSerializer,
        responses={200: serializers.AdminAccountSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = services.reactivate_account(
            admin=request.user, user_id=id, reason=serializer.validated_data["reason"],
        )
        return Response(serializers.AdminAccountSerializer(account).data)


# --------------------------------------------------------------------------
# FR-ADMIN-002: platform-wide search
# --------------------------------------------------------------------------


class PlatformSearchView(APIView):
    """GET /admin/search?q=... -- FR-ADMIN-002."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="q", type=str, location=OpenApiParameter.QUERY, required=True,
                description="Matched against user name/email, organization name, and hackathon title.",
            ),
        ],
        responses={200: serializers.PlatformSearchResultSerializer},
    )
    def get(self, request):
        results = services.platform_search(admin=request.user, query=request.query_params.get("q"))
        body = serializers.PlatformSearchResultSerializer(results).data
        return Response(body)
