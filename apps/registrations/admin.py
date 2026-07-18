from django.contrib import admin

from .models import Registration


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ("id", "hackathon", "user", "verification_status", "registered_at", "withdrawn_at")
    list_filter = ("verification_status",)
    search_fields = ("user__email", "hackathon__title")