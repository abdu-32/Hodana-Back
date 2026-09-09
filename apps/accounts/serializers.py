"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
Delegates to services.py for anything stateful.

Field names below are declared as the contract's camelCase (Doc 04); each
field's `source=` points at the model/service's snake_case name, so
`serializer.validated_data` comes out snake_case and can be passed straight
into services.py without any extra translation step.

"""

from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from apps.core.validators import validate_public_https_url

from .models import Badge

# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


class SignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    fullName = serializers.CharField(source="full_name", max_length=255, required=False, default="")


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class RefreshSerializer(serializers.Serializer):
    refreshToken = serializers.CharField(source="refresh_token")


class VerifyEmailSerializer(serializers.Serializer):
    """Not yet in Doc 04 -- FR-AUTH-003 needs an endpoint; add
    POST /auth/verify-email to the contract to match."""

    token = serializers.CharField()


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetRequestSerializer(serializers.Serializer):
    """Not yet in Doc 04 -- FR-AUTH-004 needs an endpoint; add
    POST /auth/password-reset to the contract to match."""

    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
    newPassword = serializers.CharField(source="new_password", write_only=True, trim_whitespace=False)


class OAuthLoginSerializer(serializers.Serializer):
    """POST /auth/oauth/{provider}/login -- FR-AUTH-005. `provider` itself
    comes from the URL (validated against Account.oauth_provider's choices
    in services.oauth_login), same pattern as the `id` path param on
    organizations.OrganizationVerificationReviewView -- not duplicated
    into the request body."""

    code = serializers.CharField()
    redirectUri = serializers.CharField(source="redirect_uri")


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------


class BadgeSerializer(serializers.ModelSerializer):
    userId = serializers.UUIDField(source="user_id", read_only=True)
    awardedAt = serializers.DateTimeField(source="awarded_at", read_only=True)

    class Meta:
        model = Badge
        fields = ["id", "userId", "type", "awardedAt"]


class UserProfileSerializer(serializers.Serializer):
    """Maps to Doc 04's UserProfile -- used for /users/me and nested in
    AuthResponse. Read-only: writes go through UserUpdateSerializer."""

    id = serializers.UUIDField(read_only=True)
    email = serializers.EmailField(read_only=True)
    fullName = serializers.CharField(source="full_name", read_only=True)
    bio = serializers.CharField(read_only=True)
    university = serializers.CharField(read_only=True)
    skills = serializers.ListField(child=serializers.CharField(), read_only=True)
    avatarUrl = serializers.CharField(source="avatar_url", read_only=True)
    portfolioUrl = serializers.CharField(source="portfolio_url", read_only=True)
    contactEmail = serializers.EmailField(source="contact_email", read_only=True, allow_null=True)
    dateOfBirth = serializers.DateField(source="date_of_birth", read_only=True, allow_null=True)
    country = serializers.CharField(read_only=True, allow_null=True)
    phoneNumber = serializers.CharField(source="phone_number", read_only=True)
    city = serializers.CharField(read_only=True)
    organization = serializers.CharField(read_only=True)
    department = serializers.CharField(read_only=True)
    fieldOfStudy = serializers.CharField(source="field_of_study", read_only=True)
    role = serializers.SerializerMethodField()
    profession = serializers.CharField(read_only=True)
    experienceLevel = serializers.CharField(source="experience_level", read_only=True)
    professionalTitle = serializers.CharField(source="professional_title", read_only=True)
    yearsOfExperience = serializers.IntegerField(source="years_of_experience", read_only=True, allow_null=True)
    linkedinUrl = serializers.CharField(source="linkedin_url", read_only=True)
    githubUrl = serializers.CharField(source="github_url", read_only=True)
    websiteUrl = serializers.CharField(source="website_url", read_only=True)
    twitterUrl = serializers.CharField(source="twitter_url", read_only=True)
    instagramUrl = serializers.CharField(source="instagram_url", read_only=True)
    interestedInTeams = serializers.CharField(source="interested_in_teams", read_only=True)
    lookingForTeammates = serializers.BooleanField(source="looking_for_teammates", read_only=True)
    teamSeekingDescription = serializers.CharField(source="team_seeking_description", read_only=True)
    preferredTeamRoles = serializers.ListField(child=serializers.CharField(), source="preferred_team_roles", read_only=True)
    profileVisibility = serializers.CharField(source="profile_visibility", read_only=True)
    roles = serializers.SerializerMethodField()
    organizerApplication = serializers.SerializerMethodField()
    verificationStatus = serializers.CharField(source="verification_status", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    @extend_schema_field(serializers.CharField())
    def get_role(self, account):
        if getattr(account, "is_platform_admin", False):
            return "admin"
        from apps.organizations.models import Organization
        verified_org_ids = Organization.objects.filter(
            verification_status="verified", is_suspended=False
        ).values_list("id", flat=True)
        has_verified_organizer = account.role_assignments.filter(
            role="organizer",
            scope_type="organization",
            scope_id__in=verified_org_ids,
        ).exists()
        if has_verified_organizer or getattr(account, "role", "") == "organizer":
            return "organizer"
        if account.role_assignments.filter(role="judge").exists() or getattr(account, "role", "") == "judge":
            return "judge"
        return getattr(account, "role", "participant") or "participant"

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_roles(self, account):
        roles = {"participant"}
        if getattr(account, "is_platform_admin", False):
            roles.add("admin")
            roles.add("organizer")

        from apps.organizations.models import Organization
        verified_org_ids = Organization.objects.filter(
            verification_status="verified", is_suspended=False
        ).values_list("id", flat=True)

        has_verified_organizer_role = account.role_assignments.filter(
            role="organizer",
            scope_type="organization",
            scope_id__in=verified_org_ids,
        ).exists()

        if has_verified_organizer_role:
            roles.add("organizer")

        other_roles = account.role_assignments.exclude(role="organizer").values_list("role", flat=True)
        roles.update(other_roles)
        return sorted(roles)

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_organizerApplication(self, account):
        from apps.organizations.models import Organization
        # Check organizations created by account or where account has an organizer role assignment
        org = Organization.objects.filter(created_by=account).order_by("-created_at").first()
        if not org:
            org_id = account.role_assignments.filter(
                role="organizer", scope_type="organization"
            ).values_list("scope_id", flat=True).first()
            if org_id:
                org = Organization.objects.filter(id=org_id).first()

        if not org:
            return None

        latest_review = org.verification_reviews.order_by("-reviewed_at").first()

        return {
            "id": str(org.id),
            "name": org.name,
            "type": org.type,
            "contactEmail": org.contact_email,
            "primaryEmailDomain": org.primary_email_domain,
            "verificationStatus": org.verification_status,
            "domainFastTracked": org.domain_fast_tracked,
            "isSuspended": org.is_suspended,
            "verifiedAt": org.verified_at.isoformat() if org.verified_at else None,
            "createdAt": org.created_at.isoformat() if org.created_at else None,
            "rejectionReason": latest_review.rejection_reason if (latest_review and latest_review.decision == "rejected") else None,
        }


class AuthResponseSerializer(serializers.Serializer):
    """Output-only wrapper for signup/login/refresh -- Doc 04 AuthResponse.
    `instance` is expected to be a plain dict: {"access", "refresh", "user"}."""

    accessToken = serializers.CharField(source="access")
    refreshToken = serializers.CharField(source="refresh")
    user = UserProfileSerializer()


class UserUpdateSerializer(serializers.Serializer):
    """Doc 04 UserUpdateRequest, plus extended participant profile fields.
    `validated_data` comes out snake_case, matching
    services.PROFILE_UPDATE_FIELDS exactly, so a view can pass it straight
    through to services.update_profile(account=..., data=serializer.validated_data)."""

    fullName = serializers.CharField(source="full_name", max_length=255, required=False)
    bio = serializers.CharField(max_length=500, required=False, allow_blank=True)
    university = serializers.CharField(max_length=255, required=False, allow_blank=True)
    skills = serializers.ListField(
        child=serializers.CharField(max_length=100, allow_blank=False),
        required=False,
    )
    avatarUrl = serializers.URLField(
        source="avatar_url", required=False, allow_blank=True, max_length=2048,
        validators=[validate_public_https_url],
    )
    portfolioUrl = serializers.URLField(
        source="portfolio_url", required=False, allow_blank=True, max_length=2048,
        validators=[validate_public_https_url],
    )
    contactEmail = serializers.EmailField(source="contact_email", required=False, allow_null=True)
    dateOfBirth = serializers.DateField(source="date_of_birth", required=False, allow_null=True)
    country = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=2)
    phoneNumber = serializers.CharField(source="phone_number", required=False, allow_blank=True, max_length=30)
    city = serializers.CharField(required=False, allow_blank=True, max_length=100)
    organization = serializers.CharField(required=False, allow_blank=True, max_length=255)
    department = serializers.CharField(required=False, allow_blank=True, max_length=255)
    fieldOfStudy = serializers.CharField(source="field_of_study", required=False, allow_blank=True, max_length=255)
    role = serializers.CharField(source="profession", required=False, allow_blank=True, max_length=100)
    profession = serializers.CharField(required=False, allow_blank=True, max_length=100)
    experienceLevel = serializers.CharField(source="experience_level", required=False, allow_blank=True, max_length=50)
    professionalTitle = serializers.CharField(source="professional_title", required=False, allow_blank=True, max_length=255)
    yearsOfExperience = serializers.IntegerField(source="years_of_experience", required=False, allow_null=True)
    linkedinUrl = serializers.CharField(source="linkedin_url", required=False, allow_blank=True, max_length=2048)
    githubUrl = serializers.CharField(source="github_url", required=False, allow_blank=True, max_length=2048)
    websiteUrl = serializers.CharField(source="website_url", required=False, allow_blank=True, max_length=2048)
    twitterUrl = serializers.CharField(source="twitter_url", required=False, allow_blank=True, max_length=2048)
    instagramUrl = serializers.CharField(source="instagram_url", required=False, allow_blank=True, max_length=2048)
    interestedInTeams = serializers.CharField(source="interested_in_teams", required=False, allow_blank=True, max_length=20)
    lookingForTeammates = serializers.BooleanField(source="looking_for_teammates", required=False)
    teamSeekingDescription = serializers.CharField(source="team_seeking_description", required=False, allow_blank=True)
    preferredTeamRoles = serializers.ListField(child=serializers.CharField(max_length=100), source="preferred_team_roles", required=False)
    profileVisibility = serializers.CharField(source="profile_visibility", required=False, max_length=10)

    def validate_skills(self, value):
        if len(value) > 30:
            raise serializers.ValidationError("You can list at most 30 skills.")
        return value


class PublicProfileSerializer(serializers.Serializer):
    """Doc 04 PublicProfile -- FR-PROFILE-002. Deliberately excludes email
    and phone (never rendered publicly, per the FR's acceptance criteria)."""

    id = serializers.UUIDField(read_only=True)
    fullName = serializers.CharField(source="full_name", read_only=True)
    bio = serializers.CharField(read_only=True)
    university = serializers.CharField(read_only=True)
    organization = serializers.CharField(read_only=True)
    role = serializers.CharField(source="profession", read_only=True)
    professionalTitle = serializers.CharField(source="professional_title", read_only=True)
    experienceLevel = serializers.CharField(source="experience_level", read_only=True)
    skills = serializers.ListField(child=serializers.CharField(), read_only=True)
    avatarUrl = serializers.CharField(source="avatar_url", read_only=True)
    portfolioUrl = serializers.CharField(source="portfolio_url", read_only=True)
    linkedinUrl = serializers.CharField(source="linkedin_url", read_only=True)
    githubUrl = serializers.CharField(source="github_url", read_only=True)
    websiteUrl = serializers.CharField(source="website_url", read_only=True)
    badges = BadgeSerializer(many=True, read_only=True)