"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
Delegates to services.py for anything stateful.

Field names below are declared as the contract's camelCase (Doc 04); each
field's `source=` points at the model/service's snake_case name, matching
the convention established in accounts/serializers.py.
"""

from rest_framework import serializers

from apps.core.validators import validate_public_https_url

from .models import OrgVerificationDocument, OrgVerificationReview, Organization
from .services import MAX_VERIFICATION_DOCUMENTS

# --------------------------------------------------------------------------
# Organization
# --------------------------------------------------------------------------


class OrganizationSerializer(serializers.ModelSerializer):
    """Doc 04's `Organization` schema only declares id/name/type/contactEmail
    -- missing primaryEmailDomain, verificationStatus, and verifiedAt, all of
    which are load-bearing here (FR-ORG-002's "Verified badge on every public
    page" is meaningless without exposing verification_status). Flagging as
    a contract gap to add to Doc 04/contracts/openapi.yaml rather than
    silently under-serializing to match the stale contract."""

    contactEmail = serializers.EmailField(source="contact_email", read_only=True)
    primaryEmailDomain = serializers.CharField(
        source="primary_email_domain", read_only=True, allow_null=True
    )
    verificationStatus = serializers.CharField(source="verification_status", read_only=True)
    verifiedAt = serializers.DateTimeField(source="verified_at", read_only=True)
    domainFastTracked = serializers.BooleanField(source="domain_fast_tracked", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Organization
        fields = [
            "id", "name", "type", "contactEmail", "primaryEmailDomain",
            "verificationStatus", "verifiedAt", "domainFastTracked", "createdAt",
        ]


class RegisterOrganizationSerializer(serializers.Serializer):
    """POST /organizations request body -- FR-ORG-001."""

    name = serializers.CharField(max_length=255)
    type = serializers.ChoiceField(choices=["university", "company", "ngo", "government"])
    contactEmail = serializers.EmailField(source="contact_email")
    primaryEmailDomain = serializers.CharField(
        source="primary_email_domain", required=False, allow_blank=True, allow_null=True
    )


# --------------------------------------------------------------------------
# Verification (FR-ORG-003)
# --------------------------------------------------------------------------


class OrgVerificationDocumentSerializer(serializers.ModelSerializer):
    organizationId = serializers.UUIDField(source="organization_id", read_only=True)
    fileUrl = serializers.CharField(source="file_url", read_only=True)
    uploadedByUserId = serializers.UUIDField(source="uploaded_by_id", read_only=True)
    uploadedAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = OrgVerificationDocument
        fields = ["id", "organizationId", "fileUrl", "uploadedByUserId", "uploadedAt"]


class SubmitVerificationDocumentsSerializer(serializers.Serializer):
    """POST /organizations/{id}/verification-documents -- FR-ORG-003.
    Not yet in Doc 04; add it there. `fileUrls` are object-storage pointers
    already uploaded direct-to-storage (Design Spec Sec 6.3/ADR-005), not
    raw file bytes -- this endpoint just records them. Each URL is
    validated as a well-formed https:// link to a non-internal host
    (apps.core.validators.validate_public_https_url) -- these become
    verification evidence a Platform Admin clicks through, so an
    unvalidated free-text string here was a real gap, not just a nicety.
    That check does NOT verify the URL actually resolves to a file, its
    size, or its content type -- see that validator's module docstring
    for why (nothing here receives the underlying bytes)."""

    fileUrls = serializers.ListField(
        source="file_urls",
        child=serializers.URLField(max_length=2048, validators=[validate_public_https_url]),
        min_length=1,
        max_length=MAX_VERIFICATION_DOCUMENTS,
    )


class OrgVerificationReviewSerializer(serializers.ModelSerializer):
    organizationId = serializers.UUIDField(source="organization_id", read_only=True)
    reviewedByUserId = serializers.UUIDField(source="reviewed_by_id", read_only=True)
    rejectionReason = serializers.CharField(source="rejection_reason", read_only=True)
    reviewedAt = serializers.DateTimeField(source="reviewed_at", read_only=True)

    class Meta:
        model = OrgVerificationReview
        fields = ["id", "organizationId", "reviewedByUserId", "decision", "rejectionReason", "reviewedAt"]


class ReviewOrganizationVerificationSerializer(serializers.Serializer):
    """POST /organizations/{id}/verification-review -- FR-ORG-003.
    Not yet in Doc 04; add it there."""

    decision = serializers.ChoiceField(choices=["approved", "rejected"])
    rejectionReason = serializers.CharField(
        source="rejection_reason", required=False, allow_blank=True, allow_null=True
    )

    def validate(self, attrs):
        if attrs.get("decision") == "rejected" and not attrs.get("rejection_reason"):
            raise serializers.ValidationError(
                {"rejectionReason": "Required when decision is 'rejected'."}
            )
        return attrs