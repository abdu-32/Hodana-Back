from django.contrib import admin

from .models import Notification, NotificationDelivery


class NotificationDeliveryInline(admin.TabularInline):
    model = NotificationDelivery
    extra = 0
    fields = ("user", "channel", "status", "sent_at", "read_at", "failure_reason")
    readonly_fields = ("user", "channel", "status", "sent_at", "read_at", "failure_reason")
    can_delete = False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id", "hackathon", "channel", "created_at")
    list_filter = ("channel",)
    search_fields = ("message", "hackathon__title")
    inlines = [NotificationDeliveryInline]


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):
    list_display = ("id", "notification", "user", "channel", "status", "sent_at", "read_at")
    list_filter = ("channel", "status")
    search_fields = ("user__email",)
