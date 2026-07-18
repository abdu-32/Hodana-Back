"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
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
            return [AllowAny()]
        return super().get_permissions()

    @extend_schema(responses={200: serializers.PaginatedHackathonsSerializer})
    def get(self, request):
        limit, offset = _pagination_params(request)
        results, total = services.list_hackathons(
            keyword=request.query_params.get("keyword"),
            tag=request.query_params.get("tag"),
            mode=request.query_params.get("mode"),
            status=request.query_params.get("status"),
            limit=limit, offset=offset,
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