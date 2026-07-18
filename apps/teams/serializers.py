"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
Delegates to services.py for anything stateful.
"""

from rest_framework import serializers

from .models import Team, TeamMember


class CreateTeamSerializer(serializers.Serializer):
    """POST /teams/hackathons/{hackathonId} -- FR-TEAM-001."""

    teamName = serializers.CharField(source="team_name", min_length=3, max_length=60)


class TeamSerializer(serializers.ModelSerializer):
    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True)
    teamName = serializers.CharField(source="team_name", read_only=True)
    leaderUserId = serializers.UUIDField(source="leader_user_id", read_only=True)
    openToMembers = serializers.BooleanField(source="open_to_members", read_only=True)
    maxSize = serializers.IntegerField(source="max_size", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    memberCount = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = [
            "id", "hackathonId", "teamName", "leaderUserId", "openToMembers",
            "maxSize", "createdAt", "memberCount",
        ]

    def get_memberCount(self, obj):
        return obj.members.filter(join_status="accepted").count()


class InviteMemberSerializer(serializers.Serializer):
    """POST /teams/{teamId}/invitations -- FR-TEAM-002. Invites by email
    (Account has no username field, only email -- see services.py)."""

    inviteeEmail = serializers.EmailField(source="invitee_email")


class TeamMemberSerializer(serializers.ModelSerializer):
    teamId = serializers.UUIDField(source="team_id", read_only=True)
    userId = serializers.UUIDField(source="user_id", read_only=True, allow_null=True)
    inviteeEmail = serializers.EmailField(source="invitee_email", read_only=True)
    joinStatus = serializers.CharField(source="join_status", read_only=True)
    invitedAt = serializers.DateTimeField(source="invited_at", read_only=True)
    expiresAt = serializers.DateTimeField(source="expires_at", read_only=True)
    respondedAt = serializers.DateTimeField(source="responded_at", read_only=True, allow_null=True)
    role = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        model = TeamMember
        fields = [
            "id", "teamId", "userId", "inviteeEmail", "joinStatus",
            "invitedAt", "expiresAt", "respondedAt", "role",
        ]


class TeamRosterSerializer(serializers.Serializer):
    """GET /teams/{teamId} response envelope -- FR-TEAM-005."""

    team = TeamSerializer()
    members = TeamMemberSerializer(many=True)