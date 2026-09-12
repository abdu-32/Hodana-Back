"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
Delegates to services.py for anything stateful.
"""

from rest_framework import serializers

from .models import Notification, NotificationDelivery


class NotificationCreateRequestSerializer(serializers.Serializer):
    """POST /notifications -- Doc 04 `NotificationCreateRequest`."""

    hackathonId = serializers.UUIDField(source="hackathon_id")
    title = serializers.CharField(required=False, default="")
    message = serializers.CharField()
    channel = serializers.CharField(required=False, default="in_portal")
    channels = serializers.ListField(child=serializers.CharField(), required=False, default=None)


class NotificationSerializer(serializers.ModelSerializer):
    """Doc 04 `Notification` schema -- the single broadcast resource
    returned by POST /notifications."""

    hackathonId = serializers.UUIDField(source="hackathon_id", read_only=True, allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Notification
        fields = ["id", "hackathonId", "title", "category", "message", "channel", "createdAt"]


class NotificationDeliverySerializer(serializers.ModelSerializer):
    """A single row of a user's own notification center (FR-NOTIFY-001).
    Not yet in Doc 04 -- see the "Not yet in Doc 04; add it" precedent in
    apps/registrations/views.py; add it here too once regenerated."""

    notificationId = serializers.UUIDField(source="notification_id", read_only=True)
    hackathonId = serializers.UUIDField(source="notification.hackathon_id", read_only=True, allow_null=True)
    title = serializers.SerializerMethodField()
    category = serializers.CharField(source="notification.category", read_only=True)
    message = serializers.CharField(source="notification.message", read_only=True)
    status = serializers.CharField(read_only=True)
    createdAt = serializers.DateTimeField(source="notification.created_at", read_only=True)
    readAt = serializers.DateTimeField(source="read_at", read_only=True, allow_null=True)

    class Meta:
        model = NotificationDelivery
        fields = ["id", "notificationId", "hackathonId", "title", "category", "message", "channel", "status", "createdAt", "readAt"]

    def get_title(self, obj) -> str:
        # 1. If explicit title is stored on notification, use it
        if obj.notification and obj.notification.title:
            return obj.notification.title

        # 2. Contextual fallback for existing/legacy database records
        msg = (obj.notification.message or "").strip() if obj.notification else ""
        cat = (obj.notification.category or "").lower() if obj.notification else ""

        # Remove priority tag if formatted like [URGENT] or [IMPORTANT]
        for tag in ["[URGENT]", "[IMPORTANT]", "[INFO]"]:
            if msg.startswith(tag):
                msg = msg[len(tag):].strip()

        # Split Title / Body if formatted as "Title:\nContent" or "Title - Content"
        if ":\n" in msg:
            candidate = msg.split(":\n", 1)[0].strip()
            if candidate and len(candidate) < 100:
                return candidate
        if " - " in msg:
            candidate = msg.split(" - ", 1)[0].strip()
            if candidate and len(candidate) < 80:
                return candidate

        lower_msg = msg.lower()

        # Support ticket patterns
        if "support ticket" in lower_msg or "support_ticket" in cat:
            # Per Requirement 3: Use the actual notification message if descriptive and self-contained
            if "status has been updated" in lower_msg or "has been received" in lower_msg:
                return msg
            if "new message" in lower_msg or "replied to" in lower_msg or "response" in lower_msg:
                return "Support Ticket Reply"
            return "Support Ticket Update"

        # Team patterns
        if "invited to join the team" in lower_msg or "team_invitation" in cat:
            return "Team Invitation"
        if "invitation to join" in lower_msg and ("accepted" in lower_msg or "declined" in lower_msg):
            return "Team Invitation Update"
        if "team" in lower_msg and ("member" in lower_msg or "invitation" in lower_msg or "update" in lower_msg):
            return "Team Update"

        # Email / Account verification
        if "verify your email" in lower_msg or "verification" in lower_msg or "activate your account" in lower_msg:
            return "Account Verification"
        if "password" in lower_msg and "reset" in lower_msg:
            return "Password Reset"

        # Submission patterns
        if "eligibility" in lower_msg or "eligibility" in cat:
            return "Submission Eligibility Result"
        if "deadline" in lower_msg or "deadline" in cat or ("submission" in lower_msg and "close" in lower_msg):
            return "Submission Deadline Reminder"
        if "submission" in lower_msg or "submission" in cat:
            return "Project Submission Update"

        # Judging patterns
        if "judging" in lower_msg or "judging_results" in cat:
            return "Judging Results Published"

        # Payment / Prize patterns
        if any(w in lower_msg for w in ["prize", "payout", "payment", "reward"]):
            return "Prize & Reward Notification"

        # Hackathon registrations / schedule
        if "registered for" in lower_msg or "registration_confirmation" in cat:
            return "Registration Confirmation"
        if "schedule for" in lower_msg or "timeline" in cat:
            return "Hackathon Schedule Update"

        # Hackathon announcement (ONLY if hackathon is linked)
        if obj.notification and obj.notification.hackathon_id:
            hackathon_title = getattr(obj.notification.hackathon, "title", None)
            if hackathon_title:
                return f"Announcement: {hackathon_title}"
            return "Hackathon Announcement"

        # Meaningful concise message as title (Requirement 3)
        if len(msg) <= 80 and "\n" not in msg:
            return msg

        return "Notification"
