"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.registrations.serializers import RegistrationSerializer

from . import serializers, services


class TeamCreateView(APIView):
    """POST /teams/hackathons/{hackathon_id} -- FR-TEAM-001."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=serializers.CreateTeamSerializer, responses={201: serializers.TeamSerializer})
    def post(self, request, hackathon_id):
        serializer = serializers.CreateTeamSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        team = services.create_team(
            actor=request.user, hackathon_id=hackathon_id, **serializer.validated_data,
        )
        body = serializers.TeamSerializer(team, context={"request": request}).data
        return Response(body, status=status.HTTP_201_CREATED)


class HackathonTeamsListView(APIView):
    """GET /teams/hackathons/{hackathon_id} -- list discoverable teams in hackathon."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.TeamSerializer(many=True)})
    def get(self, request, hackathon_id):
        teams = services.list_hackathon_teams(actor=request.user, hackathon_id=hackathon_id)
        return Response(serializers.TeamSerializer(teams, many=True, context={"request": request}).data)


class HackathonMyTeamStateView(APIView):
    """GET /teams/hackathons/{hackathon_id}/my-state -- unified state endpoint."""

    permission_classes = [IsAuthenticated]

    def get(self, request, hackathon_id):
        state = services.get_hackathon_team_state(actor=request.user, hackathon_id=hackathon_id)
        
        ctx = {"request": request}
        body = {
            "hackathon": {
                "id": str(state["hackathon"].id),
                "title": state["hackathon"].title,
                "slug": state["hackathon"].slug,
                "status": state["hackathon"].status,
            },
            "registration": RegistrationSerializer(state["registration"]).data if state["registration"] else None,
            "team": serializers.TeamSerializer(state["team"], context=ctx).data if state["team"] else None,
            "isLeader": state["is_leader"],
            "members": serializers.TeamMemberSerializer(state["members"], many=True, context=ctx).data,
            "pendingInvitations": serializers.TeamMemberSerializer(state["pending_invitations"], many=True, context=ctx).data,
            "pendingJoinRequests": serializers.TeamJoinRequestSerializer(state["pending_join_requests"], many=True, context=ctx).data,
            "mySentRequests": serializers.TeamJoinRequestSerializer(state["my_sent_requests"], many=True, context=ctx).data,
            "myInvitations": serializers.TeamMemberSerializer(state["my_invitations"], many=True, context=ctx).data,
            "openTeams": serializers.TeamSerializer(state["open_teams"], many=True, context=ctx).data,
        }
        return Response(body)


class TeamDetailView(APIView):
    """GET /teams/{team_id} -- FR-TEAM-005.
    PATCH /teams/{team_id} -- Update team name / description.
    DELETE /teams/{team_id} -- Delete team (leader only)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.TeamRosterSerializer})
    def get(self, request, team_id):
        team, members = services.get_team_roster(actor=request.user, team_id=team_id)
        body = {
            "team": serializers.TeamSerializer(team, context={"request": request}).data,
            "members": serializers.TeamMemberSerializer(list(members), many=True, context={"request": request}).data,
        }
        return Response(body)

    @extend_schema(request=serializers.UpdateTeamSerializer, responses={200: serializers.TeamSerializer})
    def patch(self, request, team_id):
        serializer = serializers.UpdateTeamSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        team = services.update_team(actor=request.user, team_id=team_id, **serializer.validated_data)
        return Response(serializers.TeamSerializer(team, context={"request": request}).data)

    def delete(self, request, team_id):
        services.delete_team(actor=request.user, team_id=team_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        body = serializers.TeamMemberSerializer(membership, context={"request": request}).data
        return Response(body, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: serializers.TeamMemberSerializer(many=True)})
    def get(self, request, team_id):
        invitations = list(services.list_team_invitations(actor=request.user, team_id=team_id))
        return Response(serializers.TeamMemberSerializer(invitations, many=True, context={"request": request}).data)


class CancelInvitationView(APIView):
    """DELETE /teams/invitations/{invitation_id} -- Cancel outgoing invite (owner only)."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, invitation_id):
        services.cancel_invitation(actor=request.user, invitation_id=invitation_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AcceptInvitationView(APIView):
    """POST /teams/invitations/{invitation_id}/accept -- FR-TEAM-003."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: serializers.TeamMemberSerializer})
    def post(self, request, invitation_id):
        membership = services.accept_invitation(actor=request.user, invitation_id=invitation_id)
        return Response(serializers.TeamMemberSerializer(membership, context={"request": request}).data)


class DeclineInvitationView(APIView):
    """POST /teams/invitations/{invitation_id}/decline -- FR-TEAM-003."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: serializers.TeamMemberSerializer})
    def post(self, request, invitation_id):
        membership = services.decline_invitation(actor=request.user, invitation_id=invitation_id)
        return Response(serializers.TeamMemberSerializer(membership, context={"request": request}).data)


class MyInvitationsView(APIView):
    """GET /teams/invitations/me -- pending invitations addressed to caller."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: serializers.TeamMemberSerializer(many=True)})
    def get(self, request):
        hackathon_id = request.query_params.get("hackathonId") or request.query_params.get("hackathon_id")
        invitations = list(services.list_my_invitations(actor=request.user, hackathon_id=hackathon_id))
        return Response(serializers.TeamMemberSerializer(invitations, many=True, context={"request": request}).data)


class TeamJoinRequestView(APIView):
    """POST /teams/{team_id}/join-requests -- Participant requests to join.
    GET  /teams/{team_id}/join-requests -- Leader views pending join requests."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=serializers.CreateJoinRequestSerializer, responses={201: serializers.TeamJoinRequestSerializer})
    def post(self, request, team_id):
        serializer = serializers.CreateJoinRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        join_req = services.create_join_request(
            actor=request.user, team_id=team_id, **serializer.validated_data,
        )
        return Response(serializers.TeamJoinRequestSerializer(join_req, context={"request": request}).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: serializers.TeamJoinRequestSerializer(many=True)})
    def get(self, request, team_id):
        reqs = list(services.list_team_join_requests(actor=request.user, team_id=team_id))
        return Response(serializers.TeamJoinRequestSerializer(reqs, many=True, context={"request": request}).data)


class CancelJoinRequestView(APIView):
    """DELETE /teams/join-requests/{request_id} -- Participant cancels their request."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, request_id):
        services.cancel_join_request(actor=request.user, request_id=request_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ReviewJoinRequestView(APIView):
    """POST /teams/join-requests/{request_id}/review -- Leader accepts or rejects request."""

    permission_classes = [IsAuthenticated]

    @extend_schema(request=serializers.ReviewJoinRequestSerializer, responses={200: serializers.TeamJoinRequestSerializer})
    def post(self, request, request_id):
        serializer = serializers.ReviewJoinRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        join_req = services.review_join_request(
            actor=request.user,
            request_id=request_id,
            decision=serializer.validated_data["decision"],
        )
        return Response(serializers.TeamJoinRequestSerializer(join_req, context={"request": request}).data)


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