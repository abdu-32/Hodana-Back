"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import serializers, services


def _pagination_params(request):
    try:
        limit = int(request.query_params.get("limit", 20))
    except ValueError:
        limit = 20
    try:
        offset = int(request.query_params.get("offset", 0))
    except ValueError:
        offset = 0
    return limit, offset


class HackathonShowcaseView(APIView):
    """GET /showcase/hackathons/{hackathon_id} -- FR-SHOWCASE-001 (public).
    The rank-ordered Overall and Challenge Track results for a hackathon
    whose showcase has been published; 404 while unpublished
    (services.get_hackathon_showcase)."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: serializers.HackathonShowcaseSerializer})
    def get(self, request, hackathon_id):
        showcase = services.get_hackathon_showcase(hackathon_id=hackathon_id)
        return Response(serializers.HackathonShowcaseSerializer(showcase).data)


class HackathonShowcasePublishView(APIView):
    """POST /showcase/hackathons/{hackathon_id}/publish -- FR-SHOWCASE-001.
    Makes a completed hackathon's judging results public; Organizer only,
    and only once every judging round has closed
    (services.publish_showcase)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: None})
    def post(self, request, hackathon_id):
        hackathon = services.publish_showcase(actor=request.user, hackathon_id=hackathon_id)
        return Response({"showcasePublishedAt": hackathon.showcase_published_at})


class HackathonShowcaseUnpublishView(APIView):
    """POST /showcase/hackathons/{hackathon_id}/unpublish -- FR-SHOWCASE-001
    /FR-SHOWCASE-002. Revokes public visibility of a hackathon's showcase
    page and immediately drops its projects from the cross-hackathon
    gallery; Organizer only (services.unpublish_showcase)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: None})
    def post(self, request, hackathon_id):
        services.unpublish_showcase(actor=request.user, hackathon_id=hackathon_id)
        return Response({"showcasePublishedAt": None})


class ShowcaseGalleryView(APIView):
    """GET /showcase/gallery -- FR-SHOWCASE-002 (public). A cross-hackathon,
    searchable gallery of every showcased project, filterable by
    hackathon, host institution, and technology tag
    (services.list_gallery)."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: serializers.PaginatedGallerySerializer})
    def get(self, request):
        limit, offset = _pagination_params(request)
        rows, total = services.list_gallery(
            hackathon_id=request.query_params.get("hackathonId"),
            institution_org_id=request.query_params.get("institutionOrgId"),
            tag=request.query_params.get("tag"),
            limit=limit, offset=offset,
        )
        body = {
            "data": rows,
            "meta": {"limit": limit, "offset": offset, "total": total},
        }
        return Response(serializers.PaginatedGallerySerializer(body).data)


class SubmissionShowcaseVisibilityView(APIView):
    """PUT/DELETE /showcase/submissions/{submission_id}/visibility --
    FR-SHOWCASE-001's per-submission override. PUT shows or hides one
    submission with a logged reason, overriding the eligibility-derived
    default; DELETE reverts to that default. Organizer only
    (services.set_submission_visibility / clear_submission_visibility_override)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=serializers.SubmissionVisibilitySerializer,
        responses={200: serializers.ShowcaseOverrideSerializer},
    )
    def put(self, request, submission_id):
        serializer = serializers.SubmissionVisibilitySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        override = services.set_submission_visibility(
            actor=request.user, submission_id=submission_id, **serializer.validated_data,
        )
        return Response(serializers.ShowcaseOverrideSerializer(override).data)

    @extend_schema(responses={204: None})
    def delete(self, request, submission_id):
        services.clear_submission_visibility_override(
            actor=request.user, submission_id=submission_id,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)