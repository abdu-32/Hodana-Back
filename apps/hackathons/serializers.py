"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
Delegates to services.py for anything stateful.

Field names below are declared as the contract's camelCase (Doc 04); each
field's `source=` points at the model/service's snake_case name, matching
the convention established in organizations/serializers.py.
"""

from rest_framework import serializers

from .models import ChallengeTrack, Hackathon

LOCATION_MODE_CHOICES = ["online", "in_person", "hybrid"]

# --------------------------------------------------------------------------
# Hackathon
# --------------------------------------------------------------------------


class HackathonSerializer(serializers.ModelSerializer):
    """Doc 04's `Hackathon` schema declares `eligibilityRules` as a plain
    string (it's actually JSONB per DB Design) and omits
    `showcasePublishedAt`/`updatedAt`, both load-bearing here (BR-004's
    publish gate, FR-SHOWCASE-001's visibility gate). Same "flag the
    contract gap, don't under-serialize" call as
    organizations.OrganizationSerializer."""

    hostOrgId = serializers.UUIDField(source="host_org_id", read_only=True)
    bannerUrl = serializers.CharField(source="banner_url", read_only=True, allow_blank=True)
    registrationOpensAt = serializers.DateTimeField(source="registration_opens_at", read_only=True)
    registrationClosesAt = serializers.DateTimeField(source="registration_closes_at", read_only=True)
    submissionOpensAt = serializers.DateTimeField(source="submission_opens_at", read_only=True)
    submissionClosesAt = serializers.DateTimeField(source="submission_closes_at", read_only=True)
    prizeInfo = serializers.CharField(source="prize_info", read_only=True, allow_blank=True)
    locationMode = serializers.CharField(source="location_mode", read_only=True)
    eligibilityRules = serializers.JSONField(source="eligibility_rules", read_only=True, allow_null=True)
    showcasePublishedAt = serializers.DateTimeField(source="showcase_published_at", read_only=True, allow_null=True)
    createdByUserId = serializers.UUIDField(source="created_by_id", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)
    isSuspended = serializers.BooleanField(source="is_suspended", read_only=True)  # FR-ADMIN-001

    class Meta:
        model = Hackathon
        fields = [
            "id", "title", "description", "hostOrgId", "slug", "bannerUrl",
            "registrationOpensAt", "registrationClosesAt", "submissionOpensAt", "submissionClosesAt",
            "rules", "prizeInfo", "locationMode", "eligibilityRules", "tags", "status",
            "showcasePublishedAt", "createdByUserId", "createdAt", "updatedAt", "isSuspended", 
        ]


class HackathonCreateSerializer(serializers.Serializer):
    """POST /hackathons -- FR-HACK-001. Only the contract's required set
    (title, hostOrgId, the four timeline fields) is enforced here; the
    fuller "complete hackathon" checklist (eligibility rules, rubric) is
    FR-HACK-005's publish-time gate, enforced in services.py -- see
    create_hackathon's docstring."""

    title = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    hostOrgId = serializers.UUIDField(source="host_org_id")
    slug = serializers.SlugField(max_length=255, required=False, allow_blank=True, allow_null=True)
    bannerUrl = serializers.CharField(source="banner_url", required=False, allow_blank=True, default="")
    registrationOpensAt = serializers.DateTimeField(source="registration_opens_at")
    registrationClosesAt = serializers.DateTimeField(source="registration_closes_at")
    submissionOpensAt = serializers.DateTimeField(source="submission_opens_at")
    submissionClosesAt = serializers.DateTimeField(source="submission_closes_at")
    rules = serializers.CharField(required=False, allow_blank=True, default="")
    prizeInfo = serializers.CharField(source="prize_info", required=False, allow_blank=True, default="")
    locationMode = serializers.ChoiceField(
        source="location_mode", choices=LOCATION_MODE_CHOICES, required=False, default="online",
    )
    eligibilityRules = serializers.JSONField(source="eligibility_rules", required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class HackathonUpdateSerializer(serializers.Serializer):
    """PUT /hackathons/{id} -- FR-HACK-002/003/005. All fields optional
    (partial update); `status` is how FR-HACK-005 publish/unpublish/archive
    transitions are driven, since Doc 04 has no dedicated /publish
    endpoint -- see update_hackathon's docstring."""

    title = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    bannerUrl = serializers.CharField(source="banner_url", required=False, allow_blank=True)
    registrationOpensAt = serializers.DateTimeField(source="registration_opens_at", required=False)
    registrationClosesAt = serializers.DateTimeField(source="registration_closes_at", required=False)
    submissionOpensAt = serializers.DateTimeField(source="submission_opens_at", required=False)
    submissionClosesAt = serializers.DateTimeField(source="submission_closes_at", required=False)
    rules = serializers.CharField(required=False, allow_blank=True)
    prizeInfo = serializers.CharField(source="prize_info", required=False, allow_blank=True)
    eligibilityRules = serializers.JSONField(source="eligibility_rules", required=False, allow_null=True)
    tags = serializers.ListField(child=serializers.CharField(), required=False)
    # Doc 04 only enumerates draft/published; archived added per
    # FR-HACK-005 -- flagging as a contract gap to add to Doc 04, same
    # convention as organizations' "Not yet in Doc 04; add it" comments.
    status = serializers.ChoiceField(choices=["draft", "published", "archived"], required=False)


class PaginationMetaSerializer(serializers.Serializer):
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()
    total = serializers.IntegerField()


class PaginatedHackathonsSerializer(serializers.Serializer):
    """{data, meta} envelope per Doc 04. Built manually in the view rather
    than via DRF's PageNumberPagination, since that class's
    {count,next,previous,results} shape doesn't match this contract --
    first list endpoint in the codebase, so no existing pagination
    precedent to follow instead."""

    data = HackathonSerializer(many=True)
    meta = PaginationMetaSerializer()


# --------------------------------------------------------------------------
# Challenge tracks (FR-TRACK-001/002)
# --------------------------------------------------------------------------


class ChallengeTrackSerializer(serializers.ModelSerializer):
    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True)
    sponsorOrgId = serializers.UUIDField(source="sponsor_org_id", read_only=True)
    rubricReference = serializers.CharField(source="rubric_reference", read_only=True, allow_blank=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = ChallengeTrack
        fields = ["id", "hackathonId", "sponsorOrgId", "name", "description", "prize", "rubricReference", "createdAt"]


class ChallengeTrackCreateSerializer(serializers.Serializer):
    sponsorOrgId = serializers.UUIDField(source="sponsor_org_id")
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    prize = serializers.CharField(required=False, allow_blank=True, default="")
    rubricReference = serializers.CharField(source="rubric_reference", required=False, allow_blank=True, default="")


class PaginatedChallengeTracksSerializer(serializers.Serializer):
    data = ChallengeTrackSerializer(many=True)
    meta = PaginationMetaSerializer()


# --------------------------------------------------------------------------
# Eligibility screening (FR-ELIG-001/002)
# --------------------------------------------------------------------------


class ScreeningSubmissionSerializer(serializers.Serializer):
    """Row shape for the FR-ELIG-002 bulk screening view (GET
    /hackathons/{id}/submissions). Deliberately a plain Serializer, not a
    ModelSerializer against apps.submissions.Submission -- this module
    never imports apps.submissions at module level (see services.py's
    ELIG section docstring on the import-cycle risk), so it can't
    reference the model class here either; field access instead relies
    on DRF resolving `source` against whatever submission-like object is
    passed in."""

    id = serializers.UUIDField(read_only=True)
    teamId = serializers.UUIDField(source="team_id", read_only=True)
    title = serializers.CharField(read_only=True)
    eligibilityStatus = serializers.CharField(source="eligibility_status", read_only=True)
    eligibilityReason = serializers.CharField(source="eligibility_reason", read_only=True, allow_blank=True)
    submittedAt = serializers.DateTimeField(source="submitted_at", read_only=True, allow_null=True)
    lockedAt = serializers.DateTimeField(source="locked_at", read_only=True, allow_null=True)


class PaginatedScreeningSubmissionsSerializer(serializers.Serializer):
    data = ScreeningSubmissionSerializer(many=True)
    meta = PaginationMetaSerializer()