"""
Request/response shape and field-level validation only (Design Spec Sec 3.1).
Delegates to services.py for anything stateful.
"""

from rest_framework import serializers

from .models import Notification, NotificationDelivery


class NotificationCreateRequestSerializer(serializers.Serializer):
    """POST /notifications -- Doc 04 `NotificationCreateRequest`."""

    hackathonId = serializers.UUIDField(source="hackathon_id", required=False, allow_null=True)
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
    priority = serializers.SerializerMethodField()
    category = serializers.CharField(source="notification.category", read_only=True)
    message = serializers.CharField(source="notification.message", read_only=True)
    status = serializers.CharField(read_only=True)
    createdAt = serializers.DateTimeField(source="notification.created_at", read_only=True)
    readAt = serializers.DateTimeField(source="read_at", read_only=True, allow_null=True)

    class Meta:
        model = NotificationDelivery
        fields = ["id", "notificationId", "hackathonId", "title", "priority", "category", "message", "channel", "status", "createdAt", "readAt"]

    def get_priority(self, obj) -> str:
        if not obj.notification:
            return "INFO"
        msg = (obj.notification.message or "").strip()
        lower_msg = msg.lower()
        if "[urgent]" in lower_msg or "priority: urgent" in lower_msg:
            return "URGENT"
        if "[important]" in lower_msg or "[high]" in lower_msg or "priority: high" in lower_msg or "priority: important" in lower_msg:
            return "IMPORTANT"
        return "INFO"

    def get_title(self, obj) -> str:
        stored_title = (obj.notification.title or "").strip() if obj.notification else ""
        msg = (obj.notification.message or "").strip() if obj.notification else ""
        cat = (obj.notification.category or "").lower() if obj.notification else ""
        lower_msg = msg.lower()

        # Inquiry category headlines
        INQUIRY_TITLES = {
            "technical": "Technical & Platform Bug",
            "billing": "Payments, Prizes, Billing",
            "general": "General Platform Questions",
            "hackathon_specific": "Hackathon Rules & Judging",
        }
        INQUIRY_HEADLINES = set(INQUIRY_TITLES.values())

        CANONICAL_INQUIRY_MAP = {
            "technical & platform bug": "Technical & Platform Bug",
            "payments, prizes, billing": "Payments, Prizes, Billing",
            "payments, prizes & billing": "Payments, Prizes, Billing",
            "payments & prizes": "Payments, Prizes, Billing",
            "general platform questions": "General Platform Questions",
            "general platform question": "General Platform Questions",
            "hackathon rules & judging": "Hackathon Rules & Judging",
            "hackathon rules and judging": "Hackathon Rules & Judging",
        }

        # 1. If stored_title is already an Inquiry Category headline (or legacy variant), normalize and return
        if stored_title.lower() in CANONICAL_INQUIRY_MAP:
            return CANONICAL_INQUIRY_MAP[stored_title.lower()]

        # Check if this notification is for a support ticket
        is_support = (
            cat.startswith("support")
            or "support" in cat
            or "ticket" in cat
            or "ticket" in lower_msg
            or "support" in lower_msg
            or "inquiry" in lower_msg
            or "replied to" in lower_msg
            or "submitted by" in lower_msg
            or "knowledge base" in lower_msg
            or "category: technical" in lower_msg
            or "category: billing" in lower_msg
            or "category: general" in lower_msg
            or "category: hackathon" in lower_msg
        )

        if is_support:
            # 1. Resolve from category code
            if "billing" in cat or "payment" in cat:
                return INQUIRY_TITLES["billing"]
            if "hackathon" in cat or "judging" in cat:
                return INQUIRY_TITLES["hackathon_specific"]
            if "technical" in cat or "bug" in cat:
                return INQUIRY_TITLES["technical"]
            if "general" in cat:
                return INQUIRY_TITLES["general"]

            # 2. Check message content for category lines
            if "category: technical" in lower_msg:
                return INQUIRY_TITLES["technical"]
            if "category: billing" in lower_msg or "category: payments" in lower_msg:
                return INQUIRY_TITLES["billing"]
            if "category: general" in lower_msg:
                return INQUIRY_TITLES["general"]
            if "category: hackathon" in lower_msg:
                return INQUIRY_TITLES["hackathon_specific"]

            # 3. Try to extract ticket subject from message to look up Ticket category in DB
            try:
                import re
                from apps.support.models import Ticket
                match = re.search(r"['\"]([^'\"]+)['\"]", msg)
                if match:
                    t_subject = match.group(1).strip()
                    ticket = Ticket.objects.filter(subject__iexact=t_subject).only("category").first()
                    if ticket and ticket.category in INQUIRY_TITLES:
                        return INQUIRY_TITLES[ticket.category]
            except Exception:
                pass

            # 4. Keyword heuristics for inquiry category (billing first, hackathon second, technical third, general last)
            if any(w in lower_msg for w in ["payment", "prize", "payout", "invoice", "billing", "refund", "reward"]):
                return INQUIRY_TITLES["billing"]
            if any(w in lower_msg for w in ["rules", "judging criteria", "judging", "submission requirement"]):
                return INQUIRY_TITLES["hackathon_specific"]
            if any(w in lower_msg for w in ["bug", "error", "fail", "broken", "technical", "verification", "login", "platform"]):
                return INQUIRY_TITLES["technical"]

            return INQUIRY_TITLES["general"]

        # 2. If explicit title is stored on notification and not generic, use it
        if stored_title and stored_title.lower() not in ["hackathon announcement", "notification"]:
            return stored_title

        # Remove priority tag if formatted like [URGENT] or [IMPORTANT]
        for tag in ["[URGENT]", "[IMPORTANT]", "[HIGH]", "[NORMAL]", "[INFO]", "[LOW]"]:
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

        # Platform-wide announcement or broadcast
        if obj.notification and not obj.notification.hackathon_id and ("broadcast" in cat or "platform" in cat):
            if stored_title and stored_title.lower() not in ["hackathon announcement", "notification"]:
                return stored_title
            return "Platform Announcement"

        # Hackathon update (ONLY if hackathon is linked)
        if obj.notification and obj.notification.hackathon_id:
            hackathon_title = getattr(obj.notification.hackathon, "title", None)
            if hackathon_title:
                return f"Announcement: {hackathon_title}"
            return "Hackathon Update"

        # Meaningful concise message as title
        res = "Platform Announcement"
        if len(msg) <= 80 and "\n" not in msg:
            res = msg

        if res.lower().strip() in ["hackathon announcement", "notification"]:
            if is_support:
                return INQUIRY_TITLES["general"]
            if obj.notification and obj.notification.hackathon_id:
                return "Hackathon Update"
            return "Platform Announcement"

        return res
