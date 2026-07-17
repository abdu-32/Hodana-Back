"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import HasScopedRole, IsPlatformAdmin

from . import serializers, services

# --------------------------------------------------------------------------
# Organizations
# --------------------------------------------------------------------------


class OrganizationListCreateView(APIView):
    """POST /organizations -- FR-ORG-001. Not yet in Doc 04; add it.
    No GET/list here -- there's no FR calling for a public org directory,
    only lookup-by-id (below) for badge display on pages that reference one."""

    @extend_schema(
        request=serializers.RegisterOrganizationSerializer,
        responses={201: serializers.OrganizationSerializer},
    )
    def post(self, request):
        serializer = serializers.RegisterOrganizationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        organization = services.register_organization(
            actor=request.user,
            name=data["name"],
            type=data["type"],
            contact_email=data["contact_email"],
            primary_email_domain=data.get("primary_email_domain"),
        )
        body = serializers.OrganizationSerializer(organization).data
        return Response(body, status=status.HTTP_201_CREATED)


class OrganizationDetailView(APIView):
    """GET /organizations/{id} -- not tied to a single FR by number, but
    required for the "Verified badge on every public page referencing
    them" acceptance criterion in FR-ORG-002. Not yet in Doc 04; add it.
    Public (AllowAny): the badge is meant to be visible to anonymous
    visitors browsing hackathons/orgs, same reasoning as
    accounts.UserPublicProfileView."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: serializers.OrganizationSerializer})
    def get(self, request, id):
        organization = services.get_organization(organization_id=id)
        return Response(serializers.OrganizationSerializer(organization).data)


# --------------------------------------------------------------------------
# Verification (FR-ORG-003)
# --------------------------------------------------------------------------


class OrganizationVerificationDocumentsView(APIView):
    """POST /organizations/{id}/verification-documents -- FR-ORG-003.
    Not yet in Doc 04; add it. Restricted to an Organizer scoped to this
    org (HasScopedRole checks apps.accounts.RoleAssignment, never a token
    claim, per Design Spec Sec 4.3); services.py re-checks the same thing
    for defense-in-depth, matching the pattern already used for
    is_platform_admin checks elsewhere in this codebase."""

    required_roles = ["organizer"]
    scope_type = "organization"
    scope_url_kwarg = "id"
    permission_classes = [HasScopedRole]

    @extend_schema(
        request=serializers.SubmitVerificationDocumentsSerializer,
        responses={201: serializers.OrgVerificationDocumentSerializer(many=True)},
    )
    def post(self, request, id):
        serializer = serializers.SubmitVerificationDocumentsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        documents = services.submit_verification_documents(
            actor=request.user,
            organization_id=id,
            file_urls=serializer.validated_data["file_urls"],
        )
        body = serializers.OrgVerificationDocumentSerializer(documents, many=True).data
        return Response(body, status=status.HTTP_201_CREATED)


class OrganizationVerificationReviewView(APIView):
    """POST /organizations/{id}/verification-review -- FR-ORG-003. Not yet
    in Doc 04; add it. This is the FR-ADMIN-001 dashboard's decision
    action; it lives here (not in platform_admin) because the service
    function it drives, services.review_organization_verification, is
    itself owned by this app, same reasoning as accounts owning both the
    Auth and Users tags."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ReviewOrganizationVerificationSerializer,
        responses={200: serializers.OrgVerificationReviewSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ReviewOrganizationVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        review = services.review_organization_verification(
            admin=request.user,
            organization_id=id,
            decision=data["decision"],
            rejection_reason=data.get("rejection_reason"),
        )
        return Response(serializers.OrgVerificationReviewSerializer(review).data)