"""
Request/response shape and field-level validation only (Design Spec Sec
3.1). Delegates to services.py for anything stateful.

Rows here are built from the plain dicts services.py returns (a
submission plus its team members, and -- on the hackathon showcase page
-- its round placement), not from a single ModelSerializer's Meta.model,
since no single model carries that whole shape. Same "plain Serializer
over a row shape assembled in services.py" call as
hackathons.ScreeningSubmissionSerializer.
"""

from rest_framework import serializers

from .models import ShowcaseOverride


class ShowcaseTeamMemberSerializer(serializers.Serializer):
    """One accepted team member, linking to their public profile per
    FR-PROFILE-002 -- `profileVisible` tells the frontend whether that
    link should actually be rendered (Account.profile_visibility)."""

    userId = serializers.UUIDField(source="user_id")
    fullName = serializers.CharField(source="user.full_name")
    avatarUrl = serializers.CharField(source="user.avatar_url", allow_blank=True)
    profileVisible = serializers.SerializerMethodField()

    def get_profileVisible(self, obj):
        return obj.user.profile_visibility == "public"


class ShowcaseSubmissionSerializer(serializers.Serializer):
    """A showcased project card -- FR-SHOWCASE-001's "team name, members,
    project description, media" list, minus anything BR-008 forbids
    (judge identities, raw per-judge scores)."""

    id = serializers.UUIDField()
    hackathonId = serializers.UUIDField(source="hackathon_id")
    teamId = serializers.UUIDField(source="team_id")
    teamName = serializers.CharField(source="team.team_name")
    title = serializers.CharField()
    tagline = serializers.CharField()
    description = serializers.CharField()
    technologies = serializers.ListField(child=serializers.CharField())
    repoLink = serializers.CharField(source="repo_link", allow_blank=True)
    demoVideoUrl = serializers.CharField(source="demo_video_url", allow_blank=True)
    attachmentUrls = serializers.ListField(
        source="attachment_urls", child=serializers.CharField(),
    )
    members = serializers.SerializerMethodField()

    def get_members(self, obj):
        members = self.context["team_members_by_submission"].get(obj.id, [])
        return ShowcaseTeamMemberSerializer(members, many=True).data


class ShowcaseResultRowSerializer(serializers.Serializer):
    """One row on a hackathon's showcase page: a showcased submission
    plus its placement in a judging round (FR-SHOWCASE-001)."""

    submission = serializers.SerializerMethodField()
    rank = serializers.IntegerField(allow_null=True)
    aggregateScore = serializers.DecimalField(
        source="aggregate_score", max_digits=6, decimal_places=2,
    )

    def get_submission(self, row):
        return ShowcaseSubmissionSerializer(
            row["submission"],
            context={
                "team_members_by_submission": {
                    row["submission"].id: row["team_members"],
                },
            },
        ).data


class ShowcaseTrackResultSerializer(serializers.Serializer):
    trackId = serializers.UUIDField(source="track.id")
    trackName = serializers.CharField(source="track.name")
    results = serializers.SerializerMethodField()

    def get_results(self, obj):
        return ShowcaseResultRowSerializer(obj["results"], many=True).data


class HackathonShowcaseSerializer(serializers.Serializer):
    """GET /showcase/hackathons/{id} response body."""

    hackathonId = serializers.UUIDField(source="hackathon.id")
    title = serializers.CharField(source="hackathon.title")
    slug = serializers.CharField(source="hackathon.slug")
    publishedAt = serializers.DateTimeField(source="hackathon.showcase_published_at")
    overallResults = serializers.SerializerMethodField()
    trackResults = serializers.SerializerMethodField()

    def get_overallResults(self, obj):
        return ShowcaseResultRowSerializer(obj["overall_results"], many=True).data

    def get_trackResults(self, obj):
        return ShowcaseTrackResultSerializer(obj["track_results"], many=True).data


class PaginationMetaSerializer(serializers.Serializer):
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()
    total = serializers.IntegerField()


class GalleryRowSerializer(serializers.Serializer):
    """One gallery card -- a submission plus its members, without the
    round-placement fields a single hackathon's showcase page has (a
    cross-hackathon gallery isn't scoped to any one round)."""

    def to_representation(self, row):
        return ShowcaseSubmissionSerializer(
            row["submission"],
            context={
                "team_members_by_submission": {
                    row["submission"].id: row["team_members"],
                },
            },
        ).data


class PaginatedGallerySerializer(serializers.Serializer):
    data = GalleryRowSerializer(many=True)
    meta = PaginationMetaSerializer()


class SubmissionVisibilitySerializer(serializers.Serializer):
    isVisible = serializers.BooleanField(source="is_visible")
    reason = serializers.CharField(min_length=10, max_length=2000)


class ShowcaseOverrideSerializer(serializers.ModelSerializer):
    submissionId = serializers.UUIDField(source="submission_id", read_only=True)
    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True)
    isVisible = serializers.BooleanField(source="is_visible", read_only=True)
    createdByUserId = serializers.UUIDField(source="created_by_id", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = ShowcaseOverride
        fields = [
            "id", "submissionId", "hackathonId", "isVisible", "reason",
            "createdByUserId", "createdAt",
        ]