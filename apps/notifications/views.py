"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import serializers, services


def _pagination_params(request):
    """Same pattern as apps.hackathons.views._pagination_params."""
    try:
        limit = int(request.query_params.get("limit", 20))
    except ValueError:
        limit = 20
    try:
        offset = int(request.query_params.get("offset", 0))
    except ValueError:
        offset = 0
    return limit, offset


class NotificationCreateView(APIView):
    """POST /notifications -- Doc 04 `createNotification`. Organizer-only
    (enforced in services.create_announcement, since the target
    hackathon is in the request body, not a URL kwarg -- HasScopedRole
    needs a URL kwarg to resolve scope_id from, same reasoning as
    apps.hackathons.views.HackathonListCreateView's POST)."""

    @extend_schema(
        request=serializers.NotificationCreateRequestSerializer,
        responses={201: serializers.NotificationSerializer},
    )
    def post(self, request):
        serializer = serializers.NotificationCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notification = services.create_announcement(actor=request.user, **serializer.validated_data)
        body = serializers.NotificationSerializer(notification).data
        return Response(body, status=status.HTTP_201_CREATED)


class MyNotificationsView(APIView):
    """GET /notifications/me -- FR-NOTIFY-001's notification center. Not
    yet in Doc 04; add it (same "Not yet in Doc 04" precedent as
    apps/registrations/views.py). Strictly scoped to the requester
    (services.list_my_notifications filters by actor)."""

    @extend_schema(responses={200: serializers.NotificationDeliverySerializer(many=True)})
    def get(self, request):
        limit, offset = _pagination_params(request)
        unread_only = request.query_params.get("unread") == "true"
        deliveries = list(services.list_my_notifications(actor=request.user, unread_only=unread_only))
        page = deliveries[offset:offset + limit]
        body = {
            "data": serializers.NotificationDeliverySerializer(page, many=True).data,
            "meta": {"limit": limit, "offset": offset, "total": len(deliveries)},
        }
        return Response(body)


class NotificationMarkReadView(APIView):
    """POST /notifications/me/{delivery_id}/read -- FR-NOTIFY-001: "the
    in-app notification is marked unread until the user views the
    notification center." Not yet in Doc 04; add it."""

    @extend_schema(request=None, responses={200: serializers.NotificationDeliverySerializer})
    def post(self, request, delivery_id):
        delivery = services.mark_notification_read(actor=request.user, delivery_id=delivery_id)
        return Response(serializers.NotificationDeliverySerializer(delivery).data)


class NotificationMarkAllReadView(APIView):
    """POST /notifications/me/read-all -- mark all unread notifications as read."""

    @extend_schema(request=None, responses={200: serializers.NotificationDeliverySerializer(many=True)})
    def post(self, request):
        count = services.mark_all_notifications_read(actor=request.user)
        return Response({"success": True, "count": count})
