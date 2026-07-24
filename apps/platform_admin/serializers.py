"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
Delegates to services.py for anything stateful.

Field names below are declared as the contract's camelCase (Doc 04); each
field's `source=` points at the model/service's snake_case name, matching
the convention established in organizations/serializers.py.

These serializers work directly against Account/Organization/Hackathon
(owned by other apps) rather than reusing e.g.
organizations.serializers.OrganizationSerializer -- the admin views in
this module need fields (isSuspended, an account's email) that the
public-facing serializers in those apps intentionally omit. Same
cross-app-model-from-services precedent as
organizations.services importing apps.accounts.models.RoleAssignment.
"""

from rest_framework import serializers

from apps.accounts.models import Account
from apps.hackathons.models import Hackathon
from apps.organizations.models import Organization


class ModerationActionSerializer(serializers.Serializer):
    """Request body shared by every suspend/reactivate endpoint in this
    module -- FR-ADMIN-001 requires a reason on every moderation action,
    not only on rejection (contrast with
    organizations.ReviewOrganizationVerificationSerializer, where the
    reason is conditional on the decision)."""

    reason = serializers.CharField(max_length=2000, allow_blank=False)


class AdminOrganizationSerializer(serializers.ModelSerializer):
    contactEmail = serializers.EmailField(source="contact_email", read_only=True)
    verificationStatus = serializers.CharField(source="verification_status", read_only=True)
    isSuspended = serializers.BooleanField(source="is_suspended", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "type", "contactEmail", "verificationStatus", "isSuspended", "createdAt"]


class AdminHackathonSerializer(serializers.ModelSerializer):
    hostOrgId = serializers.UUIDField(source="host_org_id", read_only=True)
    isSuspended = serializers.BooleanField(source="is_suspended", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Hackathon
        fields = ["id", "title", "slug", "hostOrgId", "status", "isSuspended", "createdAt"]


class AdminAccountSerializer(serializers.ModelSerializer):
    fullName = serializers.CharField(source="full_name", read_only=True)
    isSuspended = serializers.BooleanField(source="is_suspended", read_only=True)
    isPlatformAdmin = serializers.BooleanField(source="is_platform_admin", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Account
        fields = ["id", "email", "fullName", "isSuspended", "isPlatformAdmin", "createdAt"]


class PlatformSearchResultSerializer(serializers.Serializer):
    """Response body for GET /admin/search -- FR-ADMIN-002."""

    users = AdminAccountSerializer(many=True, read_only=True)
    organizations = AdminOrganizationSerializer(many=True, read_only=True)
    hackathons = AdminHackathonSerializer(many=True, read_only=True)
