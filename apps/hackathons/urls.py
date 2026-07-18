"""
Mounted at api/v1/hackathons/ in config/urls.py, so every path below is
relative to that prefix.
"""

from django.urls import path

from . import views

app_name = "hackathons"

urlpatterns = [
    path("", views.HackathonListCreateView.as_view(), name="list-create"),
    path("<uuid:id>", views.HackathonDetailView.as_view(), name="detail"),
    path("<uuid:id>/tracks", views.ChallengeTrackListCreateView.as_view(), name="track-list-create"),
]