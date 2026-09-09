"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
Delegates to services.py for anything stateful.
"""

from rest_framework import serializers

from .models import Team, TeamJoinRequest, TeamMember


class CreateTeamSerializer(serializers.Serializer):
    """POST /teams/hackathons/{hackathonId} -- FR-TEAM-001."""

    teamName = serializers.CharField(source="team_name", min_length=3, max_length=60)
    description = serializers.CharField(required=False, allow_blank=True, default="")


class UpdateTeamSerializer(serializers.Serializer):
    """PATCH /teams/{teamId}"""

    teamName = serializers.CharField(source="team_name", min_length=3, max_length=60, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    openToMembers = serializers.BooleanField(source="open_to_members", required=False)


class TeamSerializer(serializers.ModelSerializer):
    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True)
    hackathonTitle = serializers.CharField(source="hackathon.title", read_only=True)
    teamName = serializers.CharField(source="team_name", read_only=True)
    description = serializers.CharField(read_only=True)
    leaderUserId = serializers.UUIDField(source="leader_user_id", read_only=True)
    leaderName = serializers.SerializerMethodField()
    leaderEmail = serializers.EmailField(source="leader_user.email", read_only=True)
    openToMembers = serializers.BooleanField(source="open_to_members", read_only=True)
    maxSize = serializers.IntegerField(source="max_size", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    memberCount = serializers.SerializerMethodField()
    isLeader = serializers.SerializerMethodField()
    hasRequestedJoin = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = [
            "id", "hackathonId", "hackathonTitle", "teamName", "description",
            "leaderUserId", "leaderName", "leaderEmail", "openToMembers",
            "maxSize", "createdAt", "memberCount", "isLeader", "hasRequestedJoin",
        ]

    def get_leaderName(self, obj):
        if not obj.leader_user:
            return ""
        return getattr(obj.leader_user, "full_name", "") or obj.leader_user.email.split("@")[0]

    def get_memberCount(self, obj):
        return obj.members.filter(join_status="accepted").count()

    def get_isLeader(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.leader_user_id == request.user.id
        return False

    def get_hasRequestedJoin(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.join_requests.filter(user=request.user, status="pending").exists()
        return False


class InviteMemberSerializer(serializers.Serializer):
    """POST /teams/{teamId}/invitations -- FR-TEAM-002."""

    inviteeEmail = serializers.EmailField(source="invitee_email")


class TeamMemberSerializer(serializers.ModelSerializer):
    teamId = serializers.UUIDField(source="team_id", read_only=True)
    teamName = serializers.CharField(source="team.team_name", read_only=True)
    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True)
    hackathonTitle = serializers.CharField(source="hackathon.title", read_only=True)
    userId = serializers.UUIDField(source="user_id", read_only=True, allow_null=True)
    userName = serializers.SerializerMethodField()
    avatarUrl = serializers.CharField(source="user.avatar_url", read_only=True, allow_null=True)
    inviteeEmail = serializers.EmailField(source="invitee_email", read_only=True)
    joinStatus = serializers.CharField(source="join_status", read_only=True)
    invitedAt = serializers.DateTimeField(source="invited_at", read_only=True)
    expiresAt = serializers.DateTimeField(source="expires_at", read_only=True)
    respondedAt = serializers.DateTimeField(source="responded_at", read_only=True, allow_null=True)
    role = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        model = TeamMember
        fields = [
            "id", "teamId", "teamName", "hackathonId", "hackathonTitle",
            "userId", "userName", "avatarUrl", "inviteeEmail", "joinStatus",
            "invitedAt", "expiresAt", "respondedAt", "role",
        ]

    def get_userName(self, obj):
        if not obj.user:
            return ""
        return getattr(obj.user, "full_name", "") or obj.user.email.split("@")[0]


class CreateJoinRequestSerializer(serializers.Serializer):
    message = serializers.CharField(required=False, allow_blank=True, default="")


class ReviewJoinRequestSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["accepted", "rejected"])


class TeamJoinRequestSerializer(serializers.ModelSerializer):
    teamId = serializers.UUIDField(source="team_id", read_only=True)
    teamName = serializers.CharField(source="team.team_name", read_only=True)
    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True)
    userId = serializers.UUIDField(source="user_id", read_only=True)
    userName = serializers.SerializerMethodField()
    userEmail = serializers.EmailField(source="user.email", read_only=True)
    avatarUrl = serializers.CharField(source="user.avatar_url", read_only=True, allow_null=True)
    message = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    respondedAt = serializers.DateTimeField(source="responded_at", read_only=True, allow_null=True)

    class Meta:
        model = TeamJoinRequest
        fields = [
            "id", "teamId", "teamName", "hackathonId", "userId",
            "userName", "userEmail", "avatarUrl", "message", "status",
            "createdAt", "respondedAt",
        ]

    def get_userName(self, obj):
        if not obj.user:
            return ""
        return getattr(obj.user, "full_name", "") or obj.user.email.split("@")[0]


class TeamRosterSerializer(serializers.Serializer):
    """GET /teams/{teamId} response envelope -- FR-TEAM-005."""

    team = TeamSerializer()
    members = TeamMemberSerializer(many=True)