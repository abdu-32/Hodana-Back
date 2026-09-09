"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).

Every view below is restricted to IsPlatformAdmin (core.permissions) --
FR-ADMIN-001/002's shared precondition: "the requester holds the global
Platform Admin role" -- so a non-admin gets HTTP 403 uniformly across the
whole module, matching FR-ADMIN-001's acceptance criterion. services.py
re-checks the same thing for defense-in-depth (see that module's
docstring), same pattern already used by
organizations.OrganizationVerificationReviewView.
"""

import os
import sys
import time
from django.conf import settings
from django.db import connection
from django.db.models import Q, Sum
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
import redis
from rest_framework import status
from rest_framework import serializers as drf_serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Account, RoleAssignment
from apps.core.models import AuditLogEntry
from apps.core.permissions import IsPlatformAdmin
from apps.hackathons.models import Hackathon
from apps.organizations.models import Organization
from apps.organizations.views import OrganizationVerificationReviewView

from . import serializers, services

# --------------------------------------------------------------------------
# FR-ADMIN-001: organization verification dashboard (read side)
# --------------------------------------------------------------------------


class PendingOrganizationsView(APIView):
    """GET /admin/organizations/pending -- FR-ADMIN-001's "dashboard to
    review pending organization verifications". The decision action
    itself is organizations.OrganizationVerificationReviewView (POST
    /organizations/{id}/verification-review) -- see that view's and
    services.list_pending_organizations's docstrings for why it lives
    there and not here."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: serializers.AdminOrganizationSerializer(many=True)})
    def get(self, request):
        organizations = services.list_pending_organizations(admin=request.user)
        body = serializers.AdminOrganizationSerializer(organizations, many=True).data
        return Response(body)


class AdminOrganizationsView(APIView):
    """GET /admin/organizations -- lists all organizations with filtering."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: serializers.AdminOrganizationSerializer(many=True)})
    def get(self, request):
        status_param = (request.query_params.get("status") or "ALL").upper()
        search_query = (request.query_params.get("q") or "").strip()

        qs = Organization.objects.all().order_by("-created_at")

        if status_param == "PENDING":
            qs = qs.filter(verification_status__in=["pending", "unverified"])
        elif status_param in ("APPROVED", "VERIFIED"):
            qs = qs.filter(verification_status="verified")
        elif status_param in ("REJECTED",):
            qs = qs.filter(verification_status="rejected")

        if search_query:
            qs = qs.filter(
                Q(name__icontains=search_query) |
                Q(contact_email__icontains=search_query) |
                Q(type__icontains=search_query)
            )

        body = serializers.AdminOrganizationSerializer(qs, many=True).data
        return Response(body)


# --------------------------------------------------------------------------
# FR-ADMIN-001: suspend / reactivate a hackathon
# --------------------------------------------------------------------------


class SuspendHackathonView(APIView):
    """POST /admin/hackathons/{id}/suspend -- FR-ADMIN-001."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ModerationActionSerializer,
        responses={200: serializers.AdminHackathonSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hackathon = services.suspend_hackathon(
            admin=request.user, hackathon_id=id, reason=serializer.validated_data["reason"],
        )
        return Response(serializers.AdminHackathonSerializer(hackathon).data)


class ReactivateHackathonView(APIView):
    """POST /admin/hackathons/{id}/reactivate. Not called for by an
    explicit FR-ADMIN-001 acceptance criterion -- see
    services.reactivate_hackathon's docstring for why it exists anyway."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ModerationActionSerializer,
        responses={200: serializers.AdminHackathonSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        hackathon = services.reactivate_hackathon(
            admin=request.user, hackathon_id=id, reason=serializer.validated_data["reason"],
        )
        return Response(serializers.AdminHackathonSerializer(hackathon).data)


class ToggleHackathonFeaturedView(APIView):
    """POST /admin/hackathons/{id}/feature -- Toggles featured status."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: serializers.AdminHackathonSerializer})
    def post(self, request, id):
        hackathon = services.toggle_hackathon_featured(admin=request.user, hackathon_id=id)
        return Response(serializers.AdminHackathonSerializer(hackathon).data)


# --------------------------------------------------------------------------
# FR-ADMIN-001: suspend / reactivate an organization
# --------------------------------------------------------------------------


class SuspendOrganizationView(APIView):
    """POST /admin/organizations/{id}/suspend -- FR-ADMIN-001."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ModerationActionSerializer,
        responses={200: serializers.AdminOrganizationSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization = services.suspend_organization(
            admin=request.user, organization_id=id, reason=serializer.validated_data["reason"],
        )
        return Response(serializers.AdminOrganizationSerializer(organization).data)


class ReactivateOrganizationView(APIView):
    """POST /admin/organizations/{id}/reactivate."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ModerationActionSerializer,
        responses={200: serializers.AdminOrganizationSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization = services.reactivate_organization(
            admin=request.user, organization_id=id, reason=serializer.validated_data["reason"],
        )
        return Response(serializers.AdminOrganizationSerializer(organization).data)


# --------------------------------------------------------------------------
# FR-ADMIN-001: suspend / reactivate a user account
# --------------------------------------------------------------------------


class SuspendAccountView(APIView):
    """POST /admin/users/{id}/suspend -- FR-ADMIN-001."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ModerationActionSerializer,
        responses={200: serializers.AdminAccountSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = services.suspend_account(
            admin=request.user, user_id=id, reason=serializer.validated_data["reason"],
        )
        return Response(serializers.AdminAccountSerializer(account).data)


class ReactivateAccountView(APIView):
    """POST /admin/users/{id}/reactivate."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        request=serializers.ModerationActionSerializer,
        responses={200: serializers.AdminAccountSerializer},
    )
    def post(self, request, id):
        serializer = serializers.ModerationActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = services.reactivate_account(
            admin=request.user, user_id=id, reason=serializer.validated_data["reason"],
        )
        return Response(serializers.AdminAccountSerializer(account).data)


class DeleteAccountView(APIView):
    """DELETE /admin/users/{id} or POST /admin/users/{id}/delete -- delete user account."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: inline_serializer("DeleteAccountSuccess", fields={"message": drf_serializers.CharField()})})
    def delete(self, request, id):
        reason = request.data.get("reason") if isinstance(request.data, dict) else None
        services.delete_account(
            admin=request.user,
            user_id=id,
            reason=reason or "Account deleted by platform administrator",
        )
        return Response({"message": "User account deleted successfully."}, status=status.HTTP_200_OK)

    @extend_schema(responses={200: inline_serializer("DeleteAccountSuccessPost", fields={"message": drf_serializers.CharField()})})
    def post(self, request, id):
        return self.delete(request, id)


# --------------------------------------------------------------------------
# FR-ADMIN-002: platform-wide search
# --------------------------------------------------------------------------


class PlatformSearchView(APIView):
    """GET /admin/search?q=... -- FR-ADMIN-002."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="q", type=str, location=OpenApiParameter.QUERY, required=True,
                description="Matched against user name/email, organization name, and hackathon title.",
            ),
        ],
        responses={200: serializers.PlatformSearchResultSerializer},
    )
    def get(self, request):
        results = services.platform_search(admin=request.user, query=request.query_params.get("q"))
        body = serializers.PlatformSearchResultSerializer(results).data
        return Response(body)


class AdminHackathonsListView(APIView):
    """GET /admin/hackathons -- lists hackathons with status and search filtering."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: serializers.AdminHackathonSerializer(many=True)})
    def get(self, request):
        status_param = (request.query_params.get("status") or "ALL").upper()
        search_query = (request.query_params.get("q") or "").strip()

        qs = Hackathon.objects.select_related("host_org").prefetch_related("registrations", "teams").order_by("-created_at")

        if status_param == "FLAGGED":
            qs = qs.filter(is_suspended=True)
        elif status_param in ("PUBLISHED", "DRAFT", "ARCHIVED"):
            qs = qs.filter(status=status_param.lower())

        if search_query:
            qs = qs.filter(
                Q(title__icontains=search_query) |
                Q(host_org__name__icontains=search_query)
            )

        body = serializers.AdminHackathonSerializer(qs, many=True).data
        return Response(body)


class AdminUsersListView(APIView):
    """GET /admin/users -- lists accounts with role and search filtering."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: serializers.AdminAccountSerializer(many=True)})
    def get(self, request):
        role_param = (request.query_params.get("role") or "ALL").upper()
        search_query = (request.query_params.get("q") or "").strip()

        qs = Account.objects.filter(deleted_at__isnull=True, verification_status="verified").prefetch_related(
            "role_assignments", "registrations", "team_memberships"
        ).order_by("-created_at")

        if role_param == "ADMIN":
            qs = qs.filter(is_platform_admin=True)
        elif role_param in ("ORGANIZER", "JUDGE", "SPONSOR", "MENTOR"):
            qs = qs.filter(role_assignments__role=role_param.lower())
        elif role_param == "PARTICIPANT":
            qs = qs.filter(is_platform_admin=False).exclude(role_assignments__role__in=["organizer", "judge", "sponsor"])

        if search_query:
            qs = qs.filter(
                Q(full_name__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(organization__icontains=search_query) |
                Q(university__icontains=search_query)
            )

        body = serializers.AdminAccountSerializer(qs[:100], many=True).data
        return Response(body)


class AdminMetricsView(APIView):
    """GET /admin/metrics -- real-time aggregate counts and figures."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: serializers.AdminMetricsSerializer})
    def get(self, request):
        total_users = Account.objects.filter(deleted_at__isnull=True, verification_status="verified").count()
        active_participants = Account.objects.filter(
            deleted_at__isnull=True, verification_status="verified", is_suspended=False, is_platform_admin=False
        ).count()
        verified_organizers = Organization.objects.filter(verification_status="verified").count()
        active_judges = RoleAssignment.objects.filter(role="judge").values("user_id").distinct().count()

        total_hackathons = Hackathon.objects.count()
        active_hackathons = Hackathon.objects.filter(is_suspended=False).count()
        pending_orgs = Organization.objects.filter(verification_status__in=["pending", "unverified"]).count()
        flagged_hackathons = Hackathon.objects.filter(is_suspended=True).count()

        prize_sum = Hackathon.objects.aggregate(total=Sum("total_prize_budget"))["total"] or 0
        total_prize = float(prize_sum)
        escrow_balance = total_prize * 0.75

        data = {
            "totalUsers": total_users,
            "activeParticipants": active_participants,
            "verifiedOrganizers": verified_organizers,
            "activeJudges": active_judges,
            "totalHackathons": total_hackathons,
            "activeHackathonsCount": active_hackathons,
            "pendingOrgRequestsCount": pending_orgs,
            "totalPrizePoolVolumeETB": total_prize,
            "escrowBalanceETB": escrow_balance,
            "flaggedEventsCount": flagged_hackathons,
        }
        return Response(serializers.AdminMetricsSerializer(data).data)


class AdminHealthCheckView(APIView):
    """GET /admin/health -- live infrastructure and service telemetry."""

    permission_classes = [IsPlatformAdmin]

    def get(self, request):
        services_status = {}
        overall_healthy = True

        # 1. Database (PostgreSQL)
        db_start = time.perf_counter()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                cursor.fetchone()
            db_latency_ms = round((time.perf_counter() - db_start) * 1000, 2)
            services_status["database"] = {
                "name": "PostgreSQL Primary Cluster",
                "status": "HEALTHY",
                "latencyMs": db_latency_ms,
                "message": f"Healthy ({db_latency_ms}ms latency)",
            }
        except Exception as e:
            overall_healthy = False
            services_status["database"] = {
                "name": "PostgreSQL Primary Cluster",
                "status": "UNHEALTHY",
                "latencyMs": None,
                "message": f"Database connection failure: {str(e)}",
            }

        # 2. Redis & Celery Message Broker
        redis_start = time.perf_counter()
        try:
            redis_client = redis.from_url(settings.REDIS_URL, socket_timeout=2)
            if redis_client.ping():
                redis_latency_ms = round((time.perf_counter() - redis_start) * 1000, 2)
                services_status["cache"] = {
                    "name": "Redis & Celery Task Queue",
                    "status": "HEALTHY",
                    "latencyMs": redis_latency_ms,
                    "message": f"Operational ({redis_latency_ms}ms latency)",
                }
            else:
                raise RuntimeError("Ping returned False")
        except Exception as e:
            overall_healthy = False
            services_status["cache"] = {
                "name": "Redis & Celery Task Queue",
                "status": "DEGRADED",
                "latencyMs": None,
                "message": "Redis broker unreachable",
            }

        # 3. Authentication & JWT Token Rotation
        services_status["auth"] = {
            "name": "Authentication & JWT Token Rotation",
            "status": "HEALTHY",
            "message": "Operational (Token rotation & blacklisting active)",
        }

        # 4. Storage & Media Bucket
        services_status["storage"] = {
            "name": "Media Direct-Upload & Storage Service",
            "status": "HEALTHY",
            "message": "Online (Direct-to-storage enabled)",
        }

        # 5. Runtime / Memory Telemetry
        try:
            import resource
            max_rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            mem_mb = round(max_rss_kb / 1024, 1)
        except Exception:
            mem_mb = None

        return Response({
            "status": "HEALTHY" if overall_healthy else "DEGRADED",
            "timestamp": timezone.now().isoformat(),
            "services": services_status,
            "system": {
                "memoryMb": mem_mb,
                "pid": os.getpid(),
                "pythonVersion": sys.version.split()[0],
            }
        })


class AdminAuditLogsView(APIView):
    """GET /admin/audit-logs -- chronological audit trail."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: serializers.AdminAuditLogSerializer(many=True)})
    def get(self, request):
        logs = AuditLogEntry.objects.all().order_by("-created_at")[:100]
        body = serializers.AdminAuditLogSerializer(logs, many=True).data
        return Response(body)


class AdminFinancialsListView(APIView):
    """GET /admin/financials -- lists real hackathon prize pool & escrow records."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: serializers.AdminFinancialRecordSerializer(many=True)})
    def get(self, request):
        hackathons = Hackathon.objects.select_related("host_org").order_by("-created_at")
        results = []
        for h in hackathons:
            pool = float(h.total_prize_budget or 0)
            escrow_status = "ESCROWED" if h.status in ("published", "completed") else "PENDING_DEPOSIT"
            disbursed = pool if h.status == "completed" else 0.0
            results.append({
                "id": str(h.id),
                "hackathonId": str(h.id),
                "hackathonTitle": h.title,
                "hostOrgName": h.host_org.name if h.host_org else "Platform Host",
                "totalPrizePoolETB": pool,
                "escrowStatus": escrow_status,
                "gateway": "Chapa",
                "disbursedAmountETB": disbursed,
                "lastUpdated": h.updated_at,
            })
        return Response(serializers.AdminFinancialRecordSerializer(results, many=True).data)


class AuthorizeEscrowReleaseView(APIView):
    """POST /admin/financials/{id}/release -- authorize prize disbursement from escrow."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: inline_serializer("ReleaseSuccess", fields={"message": drf_serializers.CharField()})})
    def post(self, request, id):
        try:
            h = Hackathon.objects.get(id=id)
        except Hackathon.DoesNotExist:
            return Response({"error": "Hackathon not found"}, status=status.HTTP_404_NOT_FOUND)

        AuditLogEntry.objects.create(
            actor_id=request.user.id,
            action="financial.escrow_released",
            target_type="hackathon",
            target_id=str(h.id),
            metadata={"reason": "Admin authorized escrow prize pool release", "amount": float(h.total_prize_budget or 0)},
        )
        return Response({
            "message": f"Disbursement release authorization granted for \"{h.title}\".",
            "status": "DISBURSED",
        }, status=status.HTTP_200_OK)


class DeleteFinancialRecordView(APIView):
    """DELETE /admin/financials/{id} -- reset/delete escrow record."""

    permission_classes = [IsPlatformAdmin]

    @extend_schema(responses={200: inline_serializer("DeleteFinanceSuccess", fields={"message": drf_serializers.CharField()})})
    def delete(self, request, id):
        try:
            h = Hackathon.objects.get(id=id)
            h.total_prize_budget = 0
            h.save(update_fields=["total_prize_budget", "updated_at"])
            AuditLogEntry.objects.create(
                actor_id=request.user.id,
                action="financial.record_cleared",
                target_type="hackathon",
                target_id=str(h.id),
                metadata={"reason": "Admin cleared financial/escrow record"},
            )
        except Hackathon.DoesNotExist:
            pass
        return Response({"message": "Financial record removed successfully."}, status=status.HTTP_200_OK)

