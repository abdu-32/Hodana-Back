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
from apps.core.models import AuditLogEntry
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
    primaryEmailDomain = serializers.CharField(source="primary_email_domain", read_only=True, allow_null=True)
    verificationStatus = serializers.CharField(source="verification_status", read_only=True)
    verifiedAt = serializers.DateTimeField(source="verified_at", read_only=True, allow_null=True)
    isSuspended = serializers.BooleanField(source="is_suspended", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    domainFastTracked = serializers.BooleanField(source="domain_fast_tracked", read_only=True)
    applicantName = serializers.SerializerMethodField()
    applicantRole = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()
    latestReview = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = [
            "id", "name", "type", "contactEmail", "primaryEmailDomain", "verificationStatus",
            "verifiedAt", "domainFastTracked", "isSuspended", "createdAt",
            "applicantName", "applicantRole", "documents", "latestReview",
        ]

    def get_applicantName(self, obj):
        if getattr(obj, "created_by", None):
            return obj.created_by.full_name or obj.created_by.email.split("@")[0]
        return obj.contact_email.split("@")[0] if obj.contact_email else "Lead Representative"

    def get_applicantRole(self, obj):
        return "Lead Organizer" if getattr(obj, "created_by", None) else "Primary Contact"

    def get_documents(self, obj):
        docs = obj.verification_documents.all().order_by("-created_at")
        results = []
        for d in docs:
            name = d.file_url.split("/")[-1].split("?")[0] if d.file_url else "Verification_Doc.pdf"
            results.append({
                "id": str(d.id),
                "name": name or "Verification_Document.pdf",
                "type": "Accreditation / Registration Evidence",
                "size": "PDF / Image",
                "url": d.file_url,
                "uploadedAt": d.created_at.isoformat() if d.created_at else None,
            })
        return results

    def get_latestReview(self, obj):
        review = obj.verification_reviews.order_by("-reviewed_at").first()
        if not review:
            return None
        return {
            "decision": review.decision,
            "rejectionReason": review.rejection_reason,
            "reviewedAt": review.reviewed_at.isoformat() if review.reviewed_at else None,
            "reviewedBy": review.reviewed_by.full_name if review.reviewed_by else None,
        }


class AdminHackathonSerializer(serializers.ModelSerializer):
    hostOrgId = serializers.UUIDField(source="host_org_id", read_only=True)
    hostOrgName = serializers.SerializerMethodField()
    bannerUrl = serializers.CharField(source="banner_url", read_only=True)
    locationMode = serializers.CharField(source="location_mode", read_only=True)
    prizePool = serializers.SerializerMethodField()
    totalPrizeBudget = serializers.DecimalField(source="total_prize_budget", max_digits=12, decimal_places=2, read_only=True)
    participantsCount = serializers.SerializerMethodField()
    teamsCount = serializers.SerializerMethodField()
    startDate = serializers.DateTimeField(source="registration_opens_at", read_only=True)
    endDate = serializers.DateTimeField(source="submission_closes_at", read_only=True)
    isSuspended = serializers.BooleanField(source="is_suspended", read_only=True)
    isFeatured = serializers.SerializerMethodField()
    tags = serializers.ListField(child=serializers.CharField(), read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Hackathon
        fields = [
            "id", "title", "slug", "hostOrgId", "hostOrgName", "bannerUrl",
            "locationMode", "prizePool", "totalPrizeBudget", "participantsCount",
            "teamsCount", "status", "isSuspended", "isFeatured", "tags", "startDate", "endDate", "createdAt",
        ]

    def get_isFeatured(self, obj):
        return "Featured" in (obj.tags or [])

    def get_hostOrgName(self, obj):
        return obj.host_org.name if obj.host_org else ""

    def get_prizePool(self, obj):
        return f"{int(obj.total_prize_budget or 0):,} ETB"

    def get_participantsCount(self, obj):
        return getattr(obj, "registrations", None).count() if hasattr(obj, "registrations") else 0

    def get_teamsCount(self, obj):
        return getattr(obj, "teams", None).count() if hasattr(obj, "teams") else 0


class AdminAccountSerializer(serializers.ModelSerializer):
    fullName = serializers.CharField(source="full_name", read_only=True)
    isSuspended = serializers.BooleanField(source="is_suspended", read_only=True)
    isPlatformAdmin = serializers.BooleanField(source="is_platform_admin", read_only=True)
    verificationStatus = serializers.CharField(source="verification_status", read_only=True)
    status = serializers.SerializerMethodField()
    lastLoginAt = serializers.DateTimeField(source="last_login", read_only=True, allow_null=True)
    role = serializers.SerializerMethodField()
    affiliation = serializers.SerializerMethodField()
    hackathonsCount = serializers.SerializerMethodField()
    teamsCount = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Account
        fields = [
            "id", "email", "fullName", "role", "affiliation", "verificationStatus", "status",
            "hackathonsCount", "teamsCount", "isSuspended", "isPlatformAdmin",
            "lastLoginAt", "createdAt",
        ]

    def get_role(self, obj):
        if obj.is_platform_admin:
            return "ADMIN"
        assignment = obj.role_assignments.first()
        if assignment:
            return assignment.role.upper()
        return "PARTICIPANT"

    def get_status(self, obj):
        return "SUSPENDED" if obj.is_suspended else "ACTIVE"

    def get_affiliation(self, obj):
        return obj.organization or obj.university or "Independent Developer"

    def get_hackathonsCount(self, obj):
        return getattr(obj, "registrations", None).count() if hasattr(obj, "registrations") else 0

    def get_teamsCount(self, obj):
        return getattr(obj, "team_memberships", None).count() if hasattr(obj, "team_memberships") else 0


class AdminAuditLogSerializer(serializers.ModelSerializer):
    actorName = serializers.SerializerMethodField()
    actorEmail = serializers.SerializerMethodField()
    targetType = serializers.CharField(source="target_type", read_only=True)
    targetName = serializers.SerializerMethodField()
    details = serializers.SerializerMethodField()
    timestamp = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = AuditLogEntry
        fields = [
            "id", "actorName", "actorEmail", "action", "targetType",
            "targetName", "details", "timestamp", "metadata",
        ]

    def get_actorName(self, obj):
        if not obj.actor_id:
            return "System"
        actor = Account.objects.filter(id=obj.actor_id).first()
        return actor.full_name if actor else "Platform Administrator"

    def get_actorEmail(self, obj):
        if not obj.actor_id:
            return "system@hodana.et"
        actor = Account.objects.filter(id=obj.actor_id).first()
        return actor.email if actor else "admin@hodana.et"

    def get_targetName(self, obj):
        target_type = (obj.target_type or "").lower()
        if "organization" in target_type:
            org = Organization.objects.filter(id=obj.target_id).first()
            if org:
                return org.name
        elif "hackathon" in target_type:
            h = Hackathon.objects.filter(id=obj.target_id).first()
            if h:
                return h.title
        elif "account" in target_type or "user" in target_type:
            acc = Account.objects.filter(id=obj.target_id).first()
            if acc:
                return acc.full_name or acc.email
        return str(obj.target_id)

    def get_details(self, obj):
        meta = obj.metadata or {}
        if isinstance(meta, dict):
            if "reason" in meta and meta["reason"]:
                return f"Reason: {meta['reason']}"
            if "decision" in meta and meta["decision"]:
                return f"Decision: {meta['decision']}"
            if "query" in meta and meta["query"]:
                return f"Search query: \"{meta['query']}\""
        return f"Action {obj.action} executed"


class AdminMetricsSerializer(serializers.Serializer):
    totalUsers = serializers.IntegerField()
    activeParticipants = serializers.IntegerField()
    verifiedOrganizers = serializers.IntegerField()
    activeJudges = serializers.IntegerField()
    totalHackathons = serializers.IntegerField()
    activeHackathonsCount = serializers.IntegerField()
    pendingOrgRequestsCount = serializers.IntegerField()
    totalPrizePoolVolumeETB = serializers.FloatField()
    escrowBalanceETB = serializers.FloatField()
    flaggedEventsCount = serializers.IntegerField()


class PlatformSearchResultSerializer(serializers.Serializer):
    """Response body for GET /admin/search -- FR-ADMIN-002."""

    users = AdminAccountSerializer(many=True, read_only=True)
    organizations = AdminOrganizationSerializer(many=True, read_only=True)
    hackathons = AdminHackathonSerializer(many=True, read_only=True)


class AdminFinancialRecordSerializer(serializers.Serializer):
    id = serializers.CharField()
    hackathonId = serializers.CharField()
    hackathonTitle = serializers.CharField()
    hostOrgName = serializers.CharField()
    totalPrizePoolETB = serializers.FloatField()
    escrowStatus = serializers.CharField()
    gateway = serializers.CharField()
    disbursedAmountETB = serializers.FloatField()
    lastUpdated = serializers.DateTimeField()
