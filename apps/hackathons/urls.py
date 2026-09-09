"""
Mounted at api/v1/hackathons/ in config/urls.py, so every path below is
relative to that prefix.
"""

from django.urls import path

from . import views

app_name = "hackathons"

urlpatterns = [
    path("", views.HackathonListCreateView.as_view(), name="list-create"),
    path("export", views.HackathonExportView.as_view(), name="export-root"),
    path("export/", views.HackathonExportView.as_view(), name="export-slash"),
    path("<str:id>", views.HackathonDetailView.as_view(), name="detail"),
    path("<str:id>/export", views.HackathonExportView.as_view(), name="detail-export"),
    path("<str:id>/export/", views.HackathonExportView.as_view(), name="detail-export-slash"),
    path("<str:id>/tracks", views.ChallengeTrackListCreateView.as_view(), name="track-list-create"),
    path("<str:id>/submissions", views.HackathonSubmissionScreeningView.as_view(), name="submission-screening"),
]