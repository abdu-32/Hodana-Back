from rest_framework import serializers
from .models import Ticket, TicketMessage, InternalNote, Attachment, Assignment, TICKET_STATUS_CHOICES

class TicketMessageSerializer(serializers.ModelSerializer):
    ticketId = serializers.UUIDField(source="ticket_id", read_only=True)
    authorId = serializers.UUIDField(source="author_id", read_only=True)
    authorName = serializers.CharField(source="author.full_name", default="", read_only=True)
    authorEmail = serializers.CharField(source="author.email", default="", read_only=True)
    isStaffReply = serializers.BooleanField(source="is_staff_reply", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = TicketMessage
        fields = ["id", "ticketId", "authorId", "authorName", "authorEmail", "body", "isStaffReply", "createdAt"]


class TicketSerializer(serializers.ModelSerializer):
    submitterId = serializers.UUIDField(source="submitter_id", read_only=True)
    submitterName = serializers.CharField(source="submitter.full_name", default="", read_only=True)
    submitterEmail = serializers.CharField(source="submitter.email", default="", read_only=True)
    scopeType = serializers.CharField(source="scope_type", read_only=True)
    scopeId = serializers.UUIDField(source="scope_id", read_only=True)
    messagesCount = serializers.IntegerField(source="messages.count", read_only=True)
    lastMessage = serializers.SerializerMethodField()
    messages = TicketMessageSerializer(many=True, read_only=True)
    conversationHistory = serializers.SerializerMethodField()
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    updatedAt = serializers.DateTimeField(source="updated_at", read_only=True)

    def get_lastMessage(self, obj):
        last = obj.messages.order_by("-created_at").first()
        if not last:
            return None
        return {
            "body": last.body[:150] + ("..." if len(last.body) > 150 else ""),
            "authorName": last.author.full_name if last.author else "",
            "isStaffReply": last.is_staff_reply,
            "createdAt": last.created_at.isoformat() if last.created_at else None,
        }

    def get_conversationHistory(self, obj):
        if hasattr(obj, "get_conversation_history"):
            return obj.get_conversation_history()
        return ""

    class Meta:
        model = Ticket
        fields = [
            "id", "submitterId", "submitterName", "submitterEmail",
            "subject", "status", "priority", "category", "scopeType",
            "scopeId", "messagesCount", "lastMessage", "messages", "conversationHistory",
            "createdAt", "updatedAt"
        ]


class TicketDetailSerializer(TicketSerializer):
    """Full detail serializer including the complete conversation history between user and Platform Admin."""
    pass


class TicketCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=255)
    body = serializers.CharField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    category = serializers.CharField(max_length=50, required=False, allow_blank=True)
    problem = serializers.CharField(max_length=255, required=False, allow_blank=True)
    priority = serializers.CharField(max_length=10, required=False, default="normal")
    scopeType = serializers.CharField(required=False, allow_null=True)
    scope_type = serializers.CharField(required=False, allow_null=True)
    scopeId = serializers.UUIDField(required=False, allow_null=True)
    scope_id = serializers.UUIDField(required=False, allow_null=True)
    otherDetails = serializers.CharField(required=False, allow_blank=True)
    details = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        body = attrs.get("body") or attrs.get("description")
        if not body:
            raise serializers.ValidationError({"description": "Description or body is required."})
        attrs["body"] = body

        category = attrs.get("category") or attrs.get("problem")
        if not category:
            category = "general"
        attrs["category"] = category
        return attrs


class TicketMessageCreateSerializer(serializers.Serializer):
    ticketId = serializers.UUIDField()
    body = serializers.CharField()

class InternalNoteSerializer(serializers.ModelSerializer):
    ticketId = serializers.UUIDField(source="ticket_id", read_only=True)
    authorId = serializers.UUIDField(source="author_id", read_only=True)
    authorName = serializers.CharField(source="author.full_name", default="", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = InternalNote
        fields = ["id", "ticketId", "authorId", "authorName", "body", "createdAt"]

class InternalNoteCreateSerializer(serializers.Serializer):
    ticketId = serializers.UUIDField()
    body = serializers.CharField()

class AttachmentSerializer(serializers.ModelSerializer):
    ticketId = serializers.UUIDField(source="ticket_id", read_only=True)
    messageId = serializers.UUIDField(source="message_id", read_only=True)
    uploaderId = serializers.UUIDField(source="uploader_id", read_only=True)
    fileUrl = serializers.CharField(source="file_url", read_only=True)
    fileSize = serializers.IntegerField(source="file_size", read_only=True)
    contentType = serializers.CharField(source="content_type", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Attachment
        fields = ["id", "ticketId", "messageId", "uploaderId", "fileUrl", "filename", "fileSize", "contentType", "createdAt"]

class AttachmentCreateSerializer(serializers.Serializer):
    ticketId = serializers.UUIDField()
    messageId = serializers.UUIDField(required=False, allow_null=True)
    fileUrl = serializers.CharField()
    filename = serializers.CharField(max_length=255)
    fileSize = serializers.IntegerField()
    contentType = serializers.CharField(max_length=100)

class AssignmentSerializer(serializers.ModelSerializer):
    ticketId = serializers.UUIDField(source="ticket_id", read_only=True)
    assigneeId = serializers.UUIDField(source="assignee_id", read_only=True)
    assignedById = serializers.UUIDField(source="assigned_by_id", read_only=True)
    assignedAt = serializers.DateTimeField(source="assigned_at", read_only=True)

    class Meta:
        model = Assignment
        fields = ["id", "ticketId", "assigneeId", "assignedById", "assignedAt"]

class AssignTicketSerializer(serializers.Serializer):
    ticketId = serializers.UUIDField()
    assigneeId = serializers.UUIDField()

class StatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=TICKET_STATUS_CHOICES)

class PaginationMetaSerializer(serializers.Serializer):
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()
    total = serializers.IntegerField()

class PaginatedTicketsSerializer(serializers.Serializer):
    data = TicketSerializer(many=True)
    meta = PaginationMetaSerializer()
