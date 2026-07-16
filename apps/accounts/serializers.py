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

from .models import Badge

# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


class SignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    fullName = serializers.CharField(source="full_name", max_length=255, required=False, default="")
    oauthProvider = serializers.ChoiceField(
        source="oauth_provider", choices=["github"], required=False, allow_null=True
    )
    oauthToken = serializers.CharField(source="oauth_token", required=False, allow_blank=True)

    def validate(self, attrs):
        provider = attrs.get("oauth_provider")
        token = attrs.get("oauth_token")
        if bool(provider) != bool(token):
            raise serializers.ValidationError(
                "oauthProvider and oauthToken must be provided together."
            )
        return attrs


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
    roles = serializers.SerializerMethodField()
    verificationStatus = serializers.CharField(source="verification_status", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_roles(self, account):
        """Design Spec Sec 4.3: Participant is implicit (no RoleAssignment
        row); Platform Admin is the global boolean flag; everything else
        comes from RoleAssignment rows, deduplicated."""
        roles = {"participant"}
        if account.is_platform_admin:
            roles.add("admin")
        roles.update(account.role_assignments.values_list("role", flat=True))
        return sorted(roles)


class AuthResponseSerializer(serializers.Serializer):
    """Output-only wrapper for signup/login/refresh -- Doc 04 AuthResponse.
    `instance` is expected to be a plain dict: {"access", "refresh", "user"}."""

    accessToken = serializers.CharField(source="access")
    refreshToken = serializers.CharField(source="refresh")
    user = UserProfileSerializer()


class UserUpdateSerializer(serializers.Serializer):
    """Doc 04 UserUpdateRequest, plus portfolioUrl (see module docstring).
    `validated_data` comes out snake_case, matching
    services.PROFILE_UPDATE_FIELDS exactly, so a view can pass it straight
    through to services.update_profile(account=..., data=serializer.validated_data)."""

    fullName = serializers.CharField(source="full_name", max_length=255, required=False)
    bio = serializers.CharField(max_length=500, required=False, allow_blank=True)  # FR-PROFILE-001
    university = serializers.CharField(max_length=255, required=False, allow_blank=True)
    skills = serializers.ListField(
        child=serializers.CharField(max_length=100, allow_blank=False),
        required=False,
    )
    avatarUrl = serializers.CharField(source="avatar_url", required=False, allow_blank=True)
    portfolioUrl = serializers.URLField(source="portfolio_url", required=False, allow_blank=True)
    contactEmail = serializers.EmailField(source="contact_email", required=False, allow_null=True)

    def validate_skills(self, value):
        if len(value) > 15:  # FR-PROFILE-001
            raise serializers.ValidationError("You can list at most 15 skills.")
        return value


class PublicProfileSerializer(serializers.Serializer):
    """Doc 04 PublicProfile -- FR-PROFILE-002. Deliberately excludes email
    and phone (never rendered publicly, per the FR's acceptance criteria)."""

    id = serializers.UUIDField(read_only=True)
    fullName = serializers.CharField(source="full_name", read_only=True)
    bio = serializers.CharField(read_only=True)
    university = serializers.CharField(read_only=True)
    skills = serializers.ListField(child=serializers.CharField(), read_only=True)
    avatarUrl = serializers.CharField(source="avatar_url", read_only=True)
    portfolioUrl = serializers.CharField(source="portfolio_url", read_only=True)
    badges = BadgeSerializer(many=True, read_only=True)