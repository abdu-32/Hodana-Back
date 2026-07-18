"""
Mounted at api/v1/teams/ in config/urls.py, so every path below is
relative to that prefix.
"""

from django.urls import path

from . import views

app_name = "teams"

urlpatterns = [
    path("hackathons/<uuid:hackathon_id>", views.TeamCreateView.as_view(), name="create"),

    path("invitations/me", views.MyInvitationsView.as_view(), name="my-invitations"),
    path("invitations/<uuid:invitation_id>/accept", views.AcceptInvitationView.as_view(), name="accept-invitation"),
    path("invitations/<uuid:invitation_id>/decline", views.DeclineInvitationView.as_view(), name="decline-invitation"),

    path("<uuid:team_id>", views.TeamDetailView.as_view(), name="detail"),
    path("<uuid:team_id>/invitations", views.TeamInvitationView.as_view(), name="invitations"),
    path("<uuid:team_id>/leave", views.LeaveTeamView.as_view(), name="leave"),
    path("<uuid:team_id>/members/<uuid:user_id>", views.RemoveMemberView.as_view(), name="remove-member"),
]