from django.contrib import admin

from .models import Team, TeamMember


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("id", "team_name", "hackathon", "leader_user", "max_size", "open_to_members", "created_at")
    list_filter = ("open_to_members",)
    search_fields = ("team_name", "leader_user__email")


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ("id", "team", "user", "invitee_email", "join_status", "invited_at", "responded_at")
    list_filter = ("join_status",)
    search_fields = ("invitee_email", "user__email")