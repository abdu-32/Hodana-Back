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
        stored_title = (obj.notification.title or "").strip() if obj.notification else ""
        msg = (obj.notification.message or "").strip() if obj.notification else ""
        cat = (obj.notification.category or "").lower() if obj.notification else ""
        lower_msg = msg.lower()

        # Inquiry category headlines
        INQUIRY_TITLES = {
            "technical": "Technical & Platform Bug",
            "billing": "Payments, Prizes & Billing",
            "general": "General Platform Question",
            "hackathon_specific": "Hackathon Rules & Judging",
        }
        INQUIRY_HEADLINES = set(INQUIRY_TITLES.values())

        # 1. If stored_title is already an Inquiry Category headline, return it immediately
        if stored_title in INQUIRY_HEADLINES:
            return stored_title

        # Check if this notification is for a support ticket
        is_support = (
            cat.startswith("support")
            or "support ticket" in lower_msg
            or "ticket reference" in lower_msg
            or "support team" in lower_msg
            or "support specialist" in lower_msg
            or "replied to ticket" in lower_msg
            or "category: technical" in lower_msg
            or "category: billing" in lower_msg
            or "category: general" in lower_msg
            or "category: hackathon" in lower_msg
        )

        if is_support:
            # 1. Resolve from category code
            if "technical" in cat:
                return INQUIRY_TITLES["technical"]
            if "billing" in cat:
                return INQUIRY_TITLES["billing"]
            if "hackathon" in cat:
                return INQUIRY_TITLES["hackathon_specific"]
            if "general" in cat and "support" in cat:
                return INQUIRY_TITLES["general"]

            # 2. Check message content for category lines
            if "category: technical" in lower_msg:
                return INQUIRY_TITLES["technical"]
            if "category: billing" in lower_msg:
                return INQUIRY_TITLES["billing"]
            if "category: general" in lower_msg:
                return INQUIRY_TITLES["general"]
            if "category: hackathon" in lower_msg:
                return INQUIRY_TITLES["hackathon_specific"]

            # 3. Try to extract ticket subject from message to look up Ticket category in DB
            try:
                import re
                from apps.support.models import Ticket
                match = re.search(r"(?:ticket|regarding)\s+['\"]([^'\"]+)['\"]", msg)
                if match:
                    t_subject = match.group(1).strip()
                    ticket = Ticket.objects.filter(subject=t_subject).only("category").first()
                    if ticket and ticket.category in INQUIRY_TITLES:
                        return INQUIRY_TITLES[ticket.category]
            except Exception:
                pass

            # 4. Keyword heuristics for inquiry category
            if any(w in lower_msg for w in ["bug", "error", "fail", "broken", "issue", "technical", "verification link", "login"]):
                return INQUIRY_TITLES["technical"]
            if any(w in lower_msg for w in ["payment", "prize", "payout", "invoice", "billing", "reward"]):
                return INQUIRY_TITLES["billing"]
            if any(w in lower_msg for w in ["rules", "judging criteria", "submission requirement"]):
                return INQUIRY_TITLES["hackathon_specific"]

            return INQUIRY_TITLES["general"]

        # 2. If explicit title is stored on notification and not generic, use it
        if stored_title and stored_title.lower() not in ["hackathon announcement", "notification"]:
            return stored_title

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
