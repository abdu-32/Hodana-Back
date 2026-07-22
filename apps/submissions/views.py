"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.hackathons import services as hackathon_services
from . import serializers, services


class SubmissionUpsertView(APIView):
    """POST /submissions/hackathons/{hackathon_id} -- FR-SUB-001. Creates
    the caller's team's submission, or updates it if one already exists.
    Not yet in Doc 04/contracts/openapi.yaml -- this app owns its own url
    prefix per config/urls.py, same deviation pattern as
    apps.teams.views.TeamCreateView."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=serializers.UpsertSubmissionSerializer, responses={200: serializers.SubmissionSerializer})
    def post(self, request, hackathon_id):
        serializer = serializers.UpsertSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        submission = services.upsert_submission(
            actor=request.user, hackathon_id=hackathon_id, **serializer.validated_data,
        )
        body = serializers.SubmissionSerializer(submission).data
        return Response(body, status=status.HTTP_200_OK)


class MyHackathonSubmissionView(APIView):
    """GET /submissions/hackathons/{hackathon_id}/me -- lets the caller's
    team check whether a draft already exists before posting to
    SubmissionUpsertView."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.SubmissionSerializer})
    def get(self, request, hackathon_id):
        submission = services.get_my_submission(actor=request.user, hackathon_id=hackathon_id)
        return Response(serializers.SubmissionSerializer(submission).data)


class SubmissionDetailView(APIView):
    """GET /submissions/{submission_id} -- visible to team members and
    the hackathon's Organizer only (services._require_team_member_or_organizer)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.SubmissionSerializer})
    def get(self, request, submission_id):
        submission = services.get_submission(actor=request.user, submission_id=submission_id)
        return Response(serializers.SubmissionSerializer(submission).data)


class SubmissionMediaView(APIView):
    """POST /submissions/{submission_id}/media -- FR-SUB-002."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=serializers.AttachMediaSerializer, responses={200: serializers.SubmissionSerializer})
    def post(self, request, submission_id):
        serializer = serializers.AttachMediaSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        submission = services.attach_media(
            actor=request.user, submission_id=submission_id, **serializer.validated_data,
        )
        return Response(serializers.SubmissionSerializer(submission).data)


class SubmissionFinalizeView(APIView):
    """POST /submissions/{submission_id}/finalize -- FR-SUB-003."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: serializers.SubmissionSerializer})
    def post(self, request, submission_id):
        submission = services.finalize_submission(actor=request.user, submission_id=submission_id)
        return Response(serializers.SubmissionSerializer(submission).data)


class SubmissionHistoryView(APIView):
    """GET /submissions/{submission_id}/history -- FR-SUB-004, team
    members and the Organizer only."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.SubmissionHistorySerializer})
    def get(self, request, submission_id):
        submission, versions = services.get_submission_history(actor=request.user, submission_id=submission_id)
        body = {
            "submission": serializers.SubmissionSerializer(submission).data,
            "versions": serializers.SubmissionVersionSerializer(versions, many=True).data,
        }
        return Response(body)

class SubmissionEligibilityView(APIView):
    """PUT /submissions/{submission_id}/eligibility -- FR-ELIG-001.
    Routing only: this endpoint lives under apps.submissions' URL prefix
    (matching Doc 04's /submissions/{id}/eligibility path exactly, since
    the resource being addressed is a submission), but the screening
    business logic -- organizer permission, locked precondition, the
    10-character disqualification-reason rule, and the audit log entry --
    lives in apps.hackathons per Design Spec Sec 3.2's ELIG module
    ownership. See apps.hackathons.services.screen_submission."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=serializers.EligibilityUpdateSerializer, responses={200: serializers.SubmissionSerializer})
    def put(self, request, submission_id):
        serializer = serializers.EligibilityUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        submission = hackathon_services.screen_submission(
            actor=request.user, submission_id=submission_id, **serializer.validated_data,
        )
        return Response(serializers.SubmissionSerializer(submission).data)


class SubmissionTrackView(APIView):
    """
    POST:
        Opt a submission into a challenge track.

    DELETE:
        Remove a submission from a challenge track.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=serializers.SubmissionTrackOptInSerializer,
        responses={201: serializers.SubmissionTrackSerializer},
    )
    def post(self, request, submission_id):
        serializer = serializers.SubmissionTrackOptInSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        submission_track = services.opt_in_submission_to_track(
            submission_id=submission_id,
            track_id=serializer.validated_data["track_id"],
            actor=request.user,
        )

        return Response(
            serializers.SubmissionTrackSerializer(submission_track).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=serializers.SubmissionTrackOptInSerializer,
        responses={204: None},
    )
    def delete(self, request, submission_id):
        serializer = serializers.SubmissionTrackOptInSerializer(
            data=request.data,
        )
        serializer.is_valid(raise_exception=True)

        services.remove_submission_from_track(
            submission_id=submission_id,
            track_id=serializer.validated_data["track_id"],
            actor=request.user,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)