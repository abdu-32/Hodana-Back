"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
Delegates to services.py for anything stateful.
"""

from rest_framework import serializers

from .models import Submission, SubmissionVersion


class UpsertSubmissionSerializer(serializers.Serializer):
    """POST /submissions/hackathons/{hackathonId} -- FR-SUB-001.

    Only `title` is required here: a draft may be saved incomplete.
    FR-SUB-003's precondition ("has all required fields (FR-SUB-001)") is
    what actually gates the full title+description+at-least-one-of
    {repo,demo,media} requirement, enforced in services.finalize_submission
    -- see models.py's module docstring for the full reasoning.
    """

    title = serializers.CharField(max_length=255)
    tagline = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    description = serializers.CharField(max_length=3000, required=False, allow_blank=True, default="")
    technologies = serializers.ListField(
        child=serializers.CharField(max_length=100), required=False, default=list,
    )
    # FR-SUB-002: "must be a well-formed URL" -- validated as such even
    # though it's submitted through this create/edit endpoint rather than
    # the media-attach one, since DB Design Sec 4.6 keeps repo_link on
    # the same `submission` row as title/description.
    repoLink = serializers.URLField(source="repo_link", required=False, allow_blank=True, default="")
    demoVideoUrl = serializers.URLField(source="demo_video_url", required=False, allow_blank=True, default="")


class AttachMediaSerializer(serializers.Serializer):
    """POST /submissions/{submissionId}/media -- FR-SUB-002. Replaces the
    full attachment set (the client is expected to send the complete
    desired list, same as `technologies` above), since neither FR-SUB-002
    nor Doc 04 defines an incremental add/remove contract."""

    attachmentUrls = serializers.ListField(
        child=serializers.URLField(), source="attachment_urls", max_length=5, required=True,
    )


class SubmissionSerializer(serializers.ModelSerializer):
    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True)
    teamId = serializers.UUIDField(source="team_id", read_only=True)
    tagline = serializers.CharField(read_only=True)
    technologies = serializers.ListField(read_only=True)
    repoLink = serializers.CharField(source="repo_link", read_only=True)
    demoVideoUrl = serializers.CharField(source="demo_video_url", read_only=True)
    attachmentUrls = serializers.ListField(source="attachment_urls", read_only=True)
    eligibilityStatus = serializers.CharField(source="eligibility_status", read_only=True)
    # FR-ELIG-001: a disqualification reason must be "shown to the
    # affected team" -- exposed here since apps.submissions owns this
    # response shape even though the screening logic that writes it lives
    # in apps.hackathons (see that app's services.py ELIG section).
    eligibilityReason = serializers.CharField(source="eligibility_reason", read_only=True, allow_blank=True)
    isFinalized = serializers.BooleanField(source="is_finalized", read_only=True)
    submittedAt = serializers.DateTimeField(source="submitted_at", read_only=True)
    lockedAt = serializers.DateTimeField(source="locked_at", read_only=True, allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    class Meta:
        model = Submission
        fields = [
            "id", "hackathonId", "teamId", "title", "tagline", "description", "technologies",
            "repoLink", "demoVideoUrl", "attachmentUrls", "eligibilityStatus", "eligibilityReason",
            "isFinalized", "submittedAt", "lockedAt", "createdAt", "updatedAt",
        ]


class SubmissionVersionSerializer(serializers.ModelSerializer):
    editedByUserId = serializers.UUIDField(source="edited_by_id", read_only=True, allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = SubmissionVersion
        fields = ["id", "title", "description", "editedByUserId", "createdAt"]


class SubmissionHistorySerializer(serializers.Serializer):
    """GET /submissions/{submissionId}/history response envelope -- FR-SUB-004."""

    submission = SubmissionSerializer()
    versions = SubmissionVersionSerializer(many=True)


class EligibilityUpdateSerializer(serializers.Serializer):
    """PUT /submissions/{submissionId}/eligibility -- FR-ELIG-001. Request
    shape only; the actual screening rules (locked precondition, reason
    length, permissions, audit logging) live in
    apps.hackathons.services.screen_submission -- see that app's ELIG
    section for why ELIG logic lives there despite this being a
    submissions-prefixed endpoint."""

    eligibilityStatus = serializers.ChoiceField(
        source="eligibility_status", choices=["eligible", "disqualified"],
    )
    reason = serializers.CharField(required=False, allow_blank=True, default="")