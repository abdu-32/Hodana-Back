"""
Request/response shape and field-level validation only.
Stateful validation and cross-model rules live in services.py.
"""

from rest_framework import serializers

from .models import (
    JudgeInvitation,
    JudgingAssignment,
    JudgingCriterion,
    JudgingRound,
    RoundResult,
    Score,
)


class JudgingRoundCreateSerializer(serializers.Serializer):
    hackathonId = serializers.UUIDField(source="hackathon_id")
    trackId = serializers.UUIDField(
        source="track_id", required=False, allow_null=True,
    )


class JudgingRoundSerializer(serializers.ModelSerializer):
    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True)
    trackId = serializers.UUIDField(source="track_id", read_only=True, allow_null=True)
    openedAt = serializers.DateTimeField(source="opened_at", read_only=True, allow_null=True)
    closedAt = serializers.DateTimeField(source="closed_at", read_only=True, allow_null=True)

    class Meta:
        model = JudgingRound
        fields = ["id", "hackathonId", "trackId", "status", "openedAt", "closedAt"]


class JudgingCriterionCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    minScore = serializers.IntegerField(source="min_score", default=0)
    maxScore = serializers.IntegerField(source="max_score")
    weight = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100,
    )


class JudgingCriterionSerializer(serializers.ModelSerializer):
    roundId = serializers.UUIDField(source="round_id", read_only=True)
    minScore = serializers.IntegerField(source="min_score", read_only=True)
    maxScore = serializers.IntegerField(source="max_score", read_only=True)

    class Meta:
        model = JudgingCriterion
        fields = ["id", "roundId", "name", "minScore", "maxScore", "weight"]


class JudgeInvitationCreateSerializer(serializers.Serializer):
    email = serializers.EmailField()
    roundId = serializers.UUIDField(source="round_id", required=False, allow_null=True)
    hackathonId = serializers.UUIDField(source="hackathon_id", required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs.get("round_id") and not attrs.get("hackathon_id"):
            raise serializers.ValidationError("Either roundId or hackathonId must be provided.")
        return attrs


class JudgeInvitationSerializer(serializers.ModelSerializer):
    roundId = serializers.UUIDField(source="round_id", read_only=True)
    hackathonId = serializers.SerializerMethodField()
    hackathonTitle = serializers.SerializerMethodField()
    invitedAt = serializers.DateTimeField(source="invited_at", read_only=True)
    respondedAt = serializers.DateTimeField(
        source="responded_at", read_only=True, allow_null=True,
    )

    class Meta:
        model = JudgeInvitation
        fields = ["id", "email", "roundId", "hackathonId", "hackathonTitle", "status", "note", "invitedAt", "respondedAt"]

    def get_hackathonId(self, obj):
        return str(obj.round.hackathon_id) if obj.round and obj.round.hackathon_id else ""

    def get_hackathonTitle(self, obj):
        return obj.round.hackathon.title if obj.round and obj.round.hackathon else ""


class JudgeInvitationDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    hackathonId = serializers.SerializerMethodField()
    hackathonTitle = serializers.SerializerMethodField()
    hostOrgName = serializers.SerializerMethodField()
    status = serializers.CharField()
    note = serializers.CharField()
    invitedAt = serializers.DateTimeField(source="invited_at")
    respondedAt = serializers.DateTimeField(source="responded_at", allow_null=True)

    def get_hackathonId(self, obj):
        return str(obj.round.hackathon_id) if obj.round and obj.round.hackathon_id else ""

    def get_hackathonTitle(self, obj):
        return obj.round.hackathon.title if obj.round and obj.round.hackathon else ""

    def get_hostOrgName(self, obj):
        if obj.round and obj.round.hackathon and obj.round.hackathon.host_org:
            return obj.round.hackathon.host_org.name
        return "Event Organizer"


class OrganizerJudgeItemSerializer(serializers.Serializer):
    id = serializers.CharField()
    email = serializers.CharField()
    name = serializers.CharField()
    hackathonId = serializers.CharField()
    hackathonTitle = serializers.CharField()
    status = serializers.CharField()
    note = serializers.CharField(allow_blank=True)
    invitedAt = serializers.CharField(allow_null=True)
    respondedAt = serializers.CharField(allow_null=True)
    assignmentsCount = serializers.IntegerField()
    scoredCount = serializers.IntegerField()


class JudgeAssignedHackathonSerializer(serializers.Serializer):
    id = serializers.CharField()
    title = serializers.CharField()
    slug = serializers.CharField()
    organizerName = serializers.CharField()
    deadline = serializers.CharField()
    totalSubmissions = serializers.IntegerField()
    evaluatedSubmissions = serializers.IntegerField()
    category = serializers.CharField()
    bannerImage = serializers.CharField()


class JudgeSubmissionSerializer(serializers.Serializer):
    id = serializers.CharField()
    teamId = serializers.CharField()
    teamName = serializers.CharField()
    teamMembersCount = serializers.IntegerField()
    projectTitle = serializers.CharField()
    description = serializers.CharField()
    tagline = serializers.CharField()
    category = serializers.CharField()
    hackathonId = serializers.CharField()
    hackathonName = serializers.CharField()
    repoUrl = serializers.CharField(allow_blank=True)
    demoUrl = serializers.CharField(allow_blank=True)
    videoUrl = serializers.CharField(allow_blank=True)
    pitchDeckUrl = serializers.CharField(allow_blank=True)
    techStack = serializers.ListField(child=serializers.CharField())
    evaluationStatus = serializers.CharField()
    myEvaluation = serializers.DictField(allow_null=True, required=False)


class JudgeEvaluationSubmitSerializer(serializers.Serializer):
    hackathonId = serializers.UUIDField(source="hackathon_id", required=False, allow_null=True)
    criteriaScores = serializers.DictField(source="criteria_scores", child=serializers.FloatField())
    feedback = serializers.CharField(required=False, allow_blank=True, default="")
    status = serializers.ChoiceField(choices=["draft", "final"], required=False, default="final")



class ScoreCreateSerializer(serializers.Serializer):
    criterionId = serializers.UUIDField(source="criterion_id")
    scoreValue = serializers.IntegerField(source="score_value")
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    status = serializers.ChoiceField(
        choices=["draft", "final"], required=False, default="final",
    )


class ScoreSerializer(serializers.ModelSerializer):
    submissionId = serializers.UUIDField(source="submission_id", read_only=True)
    judgeUserId = serializers.UUIDField(source="judge_user_id", read_only=True)
    criterionId = serializers.UUIDField(source="criterion_id", read_only=True)
    scoreValue = serializers.IntegerField(source="score_value", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Score
        fields = [
            "id", "submissionId", "judgeUserId", "criterionId", "scoreValue",
            "comment", "status", "createdAt", "updatedAt",
        ]


class AssignmentCreateSerializer(serializers.Serializer):
    submissionId = serializers.UUIDField(source="submission_id")
    judgeUserId = serializers.UUIDField(source="judge_user_id")

class AssignmentChangeSerializer(serializers.Serializer):
    confirmScoreDiscard = serializers.BooleanField(
        source="confirm_score_discard", default=False,
    )


class AssignmentReassignSerializer(AssignmentChangeSerializer):
    newJudgeUserId = serializers.UUIDField(source="new_judge_user_id")


class AssignmentSerializer(serializers.ModelSerializer):
    roundId = serializers.UUIDField(source="round_id", read_only=True)
    submissionId = serializers.UUIDField(source="submission_id", read_only=True)
    judgeUserId = serializers.UUIDField(source="judge_user_id", read_only=True)
    assignedAt = serializers.DateTimeField(source="assigned_at", read_only=True)
    reassignedFromUserId = serializers.UUIDField(
        source="reassigned_from_user_id", read_only=True, allow_null=True,
    )

    class Meta:
        model = JudgingAssignment
        fields = [
            "id", "roundId", "submissionId", "judgeUserId", "assignedAt",
            "reassignedFromUserId",
        ]


class RoundResultSerializer(serializers.ModelSerializer):
    roundId = serializers.UUIDField(source="round_id", read_only=True)
    submissionId = serializers.UUIDField(source="submission_id", read_only=True)
    aggregateScore = serializers.DecimalField(
        source="aggregate_score", max_digits=6, decimal_places=2, read_only=True,
    )
    calculatedAt = serializers.DateTimeField(source="calculated_at", read_only=True)

    class Meta:
        model = RoundResult
        fields = ["id", "roundId", "submissionId", "aggregateScore", "rank", "calculatedAt"]


class AutoDistributionSerializer(serializers.Serializer):
    judgeUserIds = serializers.ListField(
        source="judge_user_ids",
        child=serializers.UUIDField(),
    )

class ScoreReopenSerializer(serializers.Serializer):
    reason = serializers.CharField(
        min_length=1,
        max_length=1000,
    )