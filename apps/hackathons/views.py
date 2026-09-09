"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).
"""

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema, OpenApiParameter
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


class HackathonListCreateView(APIView):
    """GET /hackathons -- FR-DISC-001/002 (public). POST /hackathons --
    FR-HACK-001 (organizer only; enforced in services.py since the target
    organization is in the request body, not the URL -- HasScopedRole
    needs a URL kwarg to resolve scope_id from, same reasoning as
    organizations.OrganizationListCreateView's POST)."""

    def get_permissions(self):
        if self.request.method == "GET":
            if self.request.query_params.get("managed") in ("true", "1", "True"):
                return [IsAuthenticated()]
            return [AllowAny()]
        return super().get_permissions()

    @extend_schema(responses={200: serializers.PaginatedHackathonsSerializer})
    def get(self, request):
        limit, offset = _pagination_params(request)
        managed_only = request.query_params.get("managed") in ("true", "1", "True")
        results, total = services.list_hackathons(
            keyword=request.query_params.get("keyword"),
            tag=request.query_params.get("tag"),
            mode=request.query_params.get("mode"),
            status=request.query_params.get("status"),
            field=request.query_params.get("field"),
            open_to=request.query_params.get("openTo") or request.query_params.get("open_to"),
            location=request.query_params.get("location"),
            limit=limit, offset=offset,
            requester=request.user if request.user.is_authenticated else None,
            host_org_id=request.query_params.get("hostOrgId"),
            managed_only=managed_only,
        )
        body = {
            "data": serializers.HackathonSerializer(results, many=True).data,
            "meta": {"limit": limit, "offset": offset, "total": total},
        }
        return Response(body)

    @extend_schema(
        request=serializers.HackathonCreateSerializer,
        responses={201: serializers.HackathonSerializer},
    )
    def post(self, request):
        serializer = serializers.HackathonCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hackathon = services.create_hackathon(actor=request.user, **serializer.validated_data)
        return Response(serializers.HackathonSerializer(hackathon).data, status=status.HTTP_201_CREATED)


class HackathonDetailView(APIView):
    """GET (public for published hackathons) / PUT / DELETE /hackathons/{id}."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return super().get_permissions()

    @extend_schema(responses={200: serializers.HackathonSerializer})
    def get(self, request, id):
        requester = request.user if request.user.is_authenticated else None
        hackathon = services.get_hackathon(hackathon_id=id, requester=requester)
        return Response(serializers.HackathonSerializer(hackathon).data)

    @extend_schema(
        request=serializers.HackathonUpdateSerializer,
        responses={200: serializers.HackathonSerializer},
    )
    def put(self, request, id):
        serializer = serializers.HackathonUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hackathon = services.update_hackathon(
            actor=request.user, hackathon_id=id, data=serializer.validated_data,
        )
        return Response(serializers.HackathonSerializer(hackathon).data)

    @extend_schema(responses={204: None})
    def delete(self, request, id):
        services.delete_hackathon(actor=request.user, hackathon_id=id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChallengeTrackListCreateView(APIView):
    """GET (public) / POST /hackathons/{id}/tracks -- FR-TRACK-001."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [AllowAny()]
        return super().get_permissions()

    @extend_schema(responses={200: serializers.PaginatedChallengeTracksSerializer})
    def get(self, request, id):
        tracks = list(services.list_challenge_tracks(hackathon_id=id))
        body = {
            "data": serializers.ChallengeTrackSerializer(tracks, many=True).data,
            "meta": {"limit": len(tracks), "offset": 0, "total": len(tracks)},
        }
        return Response(body)

    @extend_schema(
        request=serializers.ChallengeTrackCreateSerializer,
        responses={201: serializers.ChallengeTrackSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ChallengeTrackCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        track = services.create_challenge_track(
            actor=request.user, hackathon_id=id, **serializer.validated_data,
        )
        return Response(serializers.ChallengeTrackSerializer(track).data, status=status.HTTP_201_CREATED)
    

class HackathonSubmissionScreeningView(APIView):
    """GET /hackathons/{id}/submissions -- FR-ELIG-002 bulk screening
    view. Organizer-only (enforced in services.py, default
    IsAuthenticated permission class here, same pattern as this app's
    other organizer-gated endpoints); one-click eligible/disqualify
    actions per row are PUT /submissions/{id}/eligibility, owned by
    apps.submissions per its own URL prefix -- see that app's views.py."""

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="eligibilityStatus", type=str, location=OpenApiParameter.QUERY, required=False,
                description=f"Filter by current screening status. One of: {', '.join(services.ELIGIBILITY_STATUS_CHOICES)}.",
            ),
            OpenApiParameter(
                name="trackId", type=str, location=OpenApiParameter.QUERY, required=False,
                description="Filter to submissions opted into this ChallengeTrack. Must belong to the same hackathon.",
            ),
            OpenApiParameter(
                name="limit", type=int, location=OpenApiParameter.QUERY, required=False,
                description="Page size, 1-100. Default 20.",
            ),
            OpenApiParameter(
                name="offset", type=int, location=OpenApiParameter.QUERY, required=False,
                description="Pagination offset. Default 0.",
            ),
        ],
        responses={200: serializers.PaginatedScreeningSubmissionsSerializer},
    )
    def get(self, request, id):
        limit, offset = _pagination_params(request)
        results, total = services.list_submissions_for_screening(
            actor=request.user, hackathon_id=id,
            eligibility_status=request.query_params.get("eligibilityStatus"),
            track_id=request.query_params.get("trackId"),
            limit=limit, offset=offset,
        )
        body = {
            "data": serializers.ScreeningSubmissionSerializer(results, many=True).data,
            "meta": {"limit": limit, "offset": offset, "total": total},
        }
        return Response(body)


class HackathonExportView(APIView):
    """GET /api/v1/hackathons/export -- Unified Export Center endpoint for organizers.
    
    Supports:
    - hackathon_id: UUID or "all"
    - resource: "complete", "participants", "teams", "submissions", "judging", "prizes", "analytics"
    - format: "xlsx", "csv", "pdf"
    - contextual filters: search, status, role, city, track
    """
    permission_classes = [IsAuthenticated]

    def perform_content_negotiation(self, request, force=False):
        """Bypass DRF's default format-suffix renderer negotiation so ?format=xlsx/csv/pdf does not trigger 404."""
        from rest_framework.renderers import JSONRenderer
        return (JSONRenderer(), "application/json")

    @extend_schema(
        parameters=[
            OpenApiParameter(name="hackathonId", type=str, location=OpenApiParameter.QUERY, required=False, description="Hackathon UUID or 'all'"),
            OpenApiParameter(name="resource", type=str, location=OpenApiParameter.QUERY, required=False, description="Resource to export: complete, participants, teams, submissions, judging, prizes, analytics"),
            OpenApiParameter(name="format", type=str, location=OpenApiParameter.QUERY, required=False, description="File format: xlsx, csv, pdf"),
            OpenApiParameter(name="search", type=str, location=OpenApiParameter.QUERY, required=False, description="Text search filter"),
            OpenApiParameter(name="status", type=str, location=OpenApiParameter.QUERY, required=False, description="Status filter"),
            OpenApiParameter(name="role", type=str, location=OpenApiParameter.QUERY, required=False, description="Role filter"),
            OpenApiParameter(name="city", type=str, location=OpenApiParameter.QUERY, required=False, description="City/Location filter"),
        ],
        responses={200: None},
    )
    def get(self, request, id=None):
        hackathon_id = id or request.query_params.get("hackathonId") or request.query_params.get("hackathon_id") or "all"
        resource = request.query_params.get("resource", "complete")
        export_format = request.query_params.get("format", "xlsx")

        filters = {
            "search": request.query_params.get("search"),
            "status": request.query_params.get("status"),
            "role": request.query_params.get("role"),
            "city": request.query_params.get("city"),
            "track": request.query_params.get("track"),
        }

        result = services.export_hackathon_data(
            actor=request.user,
            hackathon_id=hackathon_id,
            resource=resource,
            format=export_format,
            filters=filters,
        )

        response = HttpResponse(
            result["content"],
            content_type=result["content_type"],
        )
        response["Content-Disposition"] = f'attachment; filename="{result["filename"]}"'
        response["Access-Control-Expose-Headers"] = "Content-Disposition"
        return response