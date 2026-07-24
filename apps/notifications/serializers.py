"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
Delegates to services.py for anything stateful.
"""

from rest_framework import serializers

from .models import Notification, NotificationDelivery


class NotificationCreateRequestSerializer(serializers.Serializer):
    """POST /notifications -- Doc 04 `NotificationCreateRequest`."""

    hackathonId = serializers.UUIDField(source="hackathon_id")
    message = serializers.CharField()
    channel = serializers.ChoiceField(choices=["email", "in_portal"], required=False, default="email")


class NotificationSerializer(serializers.ModelSerializer):
    """Doc 04 `Notification` schema -- the single broadcast resource
    returned by POST /notifications."""

    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True, allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Notification
        fields = ["id", "hackathonId", "message", "channel", "createdAt"]


class NotificationDeliverySerializer(serializers.ModelSerializer):
    """A single row of a user's own notification center (FR-NOTIFY-001).
    Not yet in Doc 04 -- see the "Not yet in Doc 04; add it" precedent in
    apps/registrations/views.py; add it here too once regenerated."""

    notificationId = serializers.UUIDField(source="notification_id", read_only=True)
    hackathonId = serializers.UUIDField(source="notification.hackathon_id", read_only=True, allow_null=True)
    message = serializers.CharField(source="notification.message", read_only=True)
    status = serializers.CharField(read_only=True)
    createdAt = serializers.DateTimeField(source="notification.created_at", read_only=True)
    readAt = serializers.DateTimeField(source="read_at", read_only=True, allow_null=True)

    class Meta:
        model = NotificationDelivery
        fields = ["id", "notificationId", "hackathonId", "message", "channel", "status", "createdAt", "readAt"]
