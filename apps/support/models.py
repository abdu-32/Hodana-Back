import uuid
from django.db import models
from apps.core.models import TimeStampedModel

TICKET_STATUS_CHOICES = [
    ("open", "Open"),
    ("pending_staff", "Pending Staff"),
    ("pending_user", "Pending User"),
    ("resolved", "Resolved"),
    ("closed", "Closed"),
]
TICKET_PRIORITY_CHOICES = [
    ("low", "Low"),
    ("normal", "Normal"),
    ("high", "High"),
    ("urgent", "Urgent"),
]
TICKET_CATEGORY_CHOICES = [
    ("technical", "Technical"),
    ("billing", "Billing"),
    ("general", "General"),
    ("hackathon_specific", "Hackathon Specific"),
]
SCOPE_TYPE_CHOICES = [
    ("hackathon", "Hackathon"),
    ("organization", "Organization"),
]

class Ticket(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    submitter = models.ForeignKey("accounts.Account", on_delete=models.SET_NULL, null=True, related_name="support_tickets_submitted")
    subject = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=TICKET_STATUS_CHOICES, default="open")
    priority = models.CharField(max_length=10, choices=TICKET_PRIORITY_CHOICES, default="normal")
    category = models.CharField(max_length=20, choices=TICKET_CATEGORY_CHOICES, default="general")
    scope_type = models.CharField(max_length=20, choices=SCOPE_TYPE_CHOICES, null=True, blank=True)
    scope_id = models.UUIDField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["submitter", "status"]),
            models.Index(fields=["status", "priority"]),
            models.Index(fields=["scope_type", "scope_id"]),
        ]

    @property
    def conversation_history(self):
        """Returns all messages in chronological order, preserving the complete thread between user and Platform Admin."""
        return self.messages.all().select_related("author").order_by("created_at")

    def get_conversation_history(self) -> str:
        """
        Formats and returns the complete conversation history between user and Platform Admin as text.
        """
        messages = list(self.conversation_history)
        if not messages:
            return "No conversation messages recorded."

        text_lines = []
        for idx, msg in enumerate(messages, 1):
            sender_role = "Platform Admin" if msg.is_staff_reply else "User"
            sender_name = msg.author.full_name if (msg.author and msg.author.full_name) else ("Specialist" if msg.is_staff_reply else "User")
            time_str = msg.created_at.strftime("%Y-%m-%d %H:%M UTC") if hasattr(msg, "created_at") and msg.created_at else ""
            text_lines.append(f"#{idx} [{time_str}] {sender_name} ({sender_role}):\n{msg.body}\n")

        return "\n--------------------------------------------------\n".join(text_lines)

    def __str__(self):
        return f"Ticket #{str(self.id)[:8]}: {self.subject} ({self.status})"

class TicketMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey("accounts.Account", on_delete=models.SET_NULL, null=True, related_name="support_messages_authored")
    body = models.TextField()
    is_staff_reply = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["ticket"]),
        ]

class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments")
    message = models.ForeignKey(TicketMessage, on_delete=models.CASCADE, null=True, blank=True, related_name="attachments")
    uploader = models.ForeignKey("accounts.Account", on_delete=models.SET_NULL, null=True, related_name="support_attachments_uploaded")
    file_url = models.TextField()
    filename = models.CharField(max_length=255)
    file_size = models.PositiveIntegerField()
    content_type = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

class InternalNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="internal_notes")
    author = models.ForeignKey("accounts.Account", on_delete=models.SET_NULL, null=True, related_name="support_notes_authored")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["ticket"]),
        ]

class Assignment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="assignments")
    assignee = models.ForeignKey("accounts.Account", on_delete=models.SET_NULL, null=True, related_name="support_tickets_assigned")
    assigned_by = models.ForeignKey("accounts.Account", on_delete=models.SET_NULL, null=True, related_name="support_assignments_made")
    assigned_at = models.DateTimeField(auto_now_add=True)
    unassigned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["ticket", "unassigned_at"]),
        ]

class StatusHistory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey("accounts.Account", on_delete=models.SET_NULL, null=True, related_name="support_status_changes_made")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
