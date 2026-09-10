from django.contrib import admin
from django.utils.html import format_html
from .models import Ticket, TicketMessage, Attachment, InternalNote, Assignment, StatusHistory


class TicketMessageInline(admin.StackedInline):
    model = TicketMessage
    extra = 0
    readonly_fields = ["created_at"]
    fields = ["created_at", "author", "is_staff_reply", "body"]
    ordering = ["created_at"]


class InternalNoteInline(admin.StackedInline):
    model = InternalNote
    extra = 0
    readonly_fields = ["created_at"]
    fields = ["created_at", "author", "body"]
    ordering = ["created_at"]


class StatusHistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0
    readonly_fields = ["created_at", "from_status", "to_status", "actor"]
    fields = ["created_at", "from_status", "to_status", "actor"]
    can_delete = False
    ordering = ["created_at"]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = [
        "short_id", "subject", "submitter", "status", "priority",
        "category", "messages_count", "created_at", "updated_at"
    ]
    list_filter = ["status", "priority", "category", "created_at"]
    search_fields = ["id", "subject", "submitter__email", "submitter__full_name"]
    readonly_fields = ["id", "created_at", "updated_at", "conversation_history_display"]
    inlines = [TicketMessageInline, InternalNoteInline, StatusHistoryInline]

    fieldsets = [
        ("Ticket Overview", {
            "fields": ["id", "submitter", "subject", "status", "priority", "category", "scope_type", "scope_id"]
        }),
        ("Complete Conversation History", {
            "fields": ["conversation_history_display"],
        }),
        ("Timestamps", {
            "fields": ["created_at", "updated_at"]
        }),
    ]

    def short_id(self, obj):
        return str(obj.id)[:8]
    short_id.short_description = "ID"

    def messages_count(self, obj):
        return obj.messages.count()
    messages_count.short_description = "Messages"

    def conversation_history_display(self, obj):
        if not obj or not obj.id:
            return "No conversation history available."
        messages = list(obj.messages.select_related("author").order_by("created_at"))
        if not messages:
            return "No messages recorded in this ticket."

        items = []
        for idx, msg in enumerate(messages, 1):
            role = "Platform Admin" if msg.is_staff_reply else "User"
            color = "#0f6b5c" if msg.is_staff_reply else "#1e40af"
            bg = "#ecfdf5" if msg.is_staff_reply else "#eff6ff"
            name = msg.author.full_name if (msg.author and msg.author.full_name) else ("Specialist" if msg.is_staff_reply else "User")
            time_str = msg.created_at.strftime("%Y-%m-%d %H:%M UTC") if msg.created_at else ""

            items.append(
                f'<div style="margin-bottom: 12px; padding: 12px 14px; border-radius: 8px; background: {bg}; border-left: 4px solid {color};">'
                f'<div style="font-weight: bold; font-size: 12px; color: {color}; margin-bottom: 4px;">'
                f'#{idx} {name} ({role}) <span style="font-size: 11px; color: #64748b; font-weight: normal; margin-left: 8px;">{time_str}</span>'
                f'</div>'
                f'<div style="font-size: 13px; color: #1e293b; white-space: pre-wrap;">{msg.body}</div>'
                f'</div>'
            )
        return format_html("".join(items))
    conversation_history_display.short_description = "Conversation Thread"


@admin.register(TicketMessage)
class TicketMessageAdmin(admin.ModelAdmin):
    list_display = ["id", "ticket", "author", "is_staff_reply", "created_at"]
    list_filter = ["is_staff_reply", "created_at"]
    search_fields = ["ticket__id", "body", "author__email"]


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ["filename", "ticket", "uploader", "file_size", "created_at"]


@admin.register(InternalNote)
class InternalNoteAdmin(admin.ModelAdmin):
    list_display = ["id", "ticket", "author", "created_at"]
    search_fields = ["ticket__id", "body"]


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ["ticket", "assignee", "assigned_by", "assigned_at", "unassigned_at"]


@admin.register(StatusHistory)
class StatusHistoryAdmin(admin.ModelAdmin):
    list_display = ["ticket", "from_status", "to_status", "actor", "created_at"]

