"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
"""

from rest_framework import serializers

from .models import Registration


class RegisterForHackathonSerializer(serializers.Serializer):
    """POST /registrations/hackathons/{hackathonId} -- FR-REG-001."""

    eligibilityConfirmed = serializers.BooleanField(
        source="eligibility_confirmed", required=False, default=False,
    )
    customAnswers = serializers.JSONField(
        source="custom_answers", required=False, allow_null=True,
    )


class RegistrationSerializer(serializers.ModelSerializer):
    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True)
    userId = serializers.UUIDField(source="user_id", read_only=True)
    eligibilityConfirmed = serializers.BooleanField(source="eligibility_confirmed", read_only=True)
    customAnswers = serializers.JSONField(source="custom_answers", read_only=True)
    verificationStatus = serializers.CharField(source="verification_status", read_only=True)
    registeredAt = serializers.DateTimeField(source="registered_at", read_only=True)
    withdrawnAt = serializers.DateTimeField(source="withdrawn_at", read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = Registration
        fields = [
            "id", "hackathonId", "userId", "eligibilityConfirmed", "customAnswers",
            "verificationStatus", "registeredAt", "withdrawnAt", "status",
        ]