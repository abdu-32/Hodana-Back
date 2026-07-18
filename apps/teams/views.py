"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import serializers, services


class TeamCreateView(APIView):
    """POST /teams/hackathons/{hackathon_id} -- FR-TEAM-001.
    Not yet in Doc 04/contracts/openapi.yaml -- this app owns its own url
    prefix per config/urls.py, same deviation pattern as
    apps.registrations.views.HackathonRegistrationView."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=serializers.CreateTeamSerializer, responses={201: serializers.TeamSerializer})
    def post(self, request, hackathon_id):
        serializer = serializers.CreateTeamSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        team = services.create_team(
            actor=request.user, hackathon_id=hackathon_id, **serializer.validated_data,
        )
        body = serializers.TeamSerializer(team).data
        return Response(body, status=status.HTTP_201_CREATED)


class TeamDetailView(APIView):
    """GET /teams/{team_id} -- FR-TEAM-005. Roster visible only to team
    members and the hackathon's Organizer; anyone else gets 403."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.TeamRosterSerializer})
    def get(self, request, team_id):
        team, members = services.get_team_roster(actor=request.user, team_id=team_id)
        body = {
            "team": serializers.TeamSerializer(team).data,
            "members": serializers.TeamMemberSerializer(list(members), many=True).data,
        }
        return Response(body)


class TeamInvitationView(APIView):
    """POST /teams/{team_id}/invitations -- FR-TEAM-002.
    GET  /teams/{team_id}/invitations -- pending invitations, owner-only."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=serializers.InviteMemberSerializer, responses={201: serializers.TeamMemberSerializer})
    def post(self, request, team_id):
        serializer = serializers.InviteMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        membership = services.invite_member(
            actor=request.user, team_id=team_id, **serializer.validated_data,
        )
        body = serializers.TeamMemberSerializer(membership).data
        return Response(body, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: serializers.TeamMemberSerializer(many=True)})
    def get(self, request, team_id):
        invitations = list(services.list_team_invitations(actor=request.user, team_id=team_id))
        return Response(serializers.TeamMemberSerializer(invitations, many=True).data)


class AcceptInvitationView(APIView):
    """POST /teams/invitations/{invitation_id}/accept -- FR-TEAM-003."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: serializers.TeamMemberSerializer})
    def post(self, request, invitation_id):
        membership = services.accept_invitation(actor=request.user, invitation_id=invitation_id)
        return Response(serializers.TeamMemberSerializer(membership).data)


class DeclineInvitationView(APIView):
    """POST /teams/invitations/{invitation_id}/decline -- FR-TEAM-003."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: serializers.TeamMemberSerializer})
    def post(self, request, invitation_id):
        membership = services.decline_invitation(actor=request.user, invitation_id=invitation_id)
        return Response(serializers.TeamMemberSerializer(membership).data)


class MyInvitationsView(APIView):
    """GET /teams/invitations/me -- pending invitations addressed to the
    caller, across all hackathons. Strictly scoped to the requester, same
    pattern as apps.registrations.views.MyRegistrationsView."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.TeamMemberSerializer(many=True)})
    def get(self, request):
        invitations = list(services.list_my_invitations(actor=request.user))
        return Response(serializers.TeamMemberSerializer(invitations, many=True).data)


class LeaveTeamView(APIView):
    """POST /teams/{team_id}/leave -- FR-TEAM-004."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request, team_id):
        services.leave_team(actor=request.user, team_id=team_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RemoveMemberView(APIView):
    """DELETE /teams/{team_id}/members/{user_id} -- FR-TEAM-004, owner-only."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request, team_id, user_id):
        services.remove_member(actor=request.user, team_id=team_id, member_user_id=user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)