"""
Mounted at api/v1/submissions/ in config/urls.py, so every path below is
relative to that prefix.
"""

from django.urls import path

from . import views

app_name = "submissions"

urlpatterns = [
    path("hackathons/<uuid:hackathon_id>", views.SubmissionUpsertView.as_view(), name="upsert"),
    path("hackathons/<uuid:hackathon_id>/me", views.MyHackathonSubmissionView.as_view(), name="my-submission"),

    path("<uuid:submission_id>", views.SubmissionDetailView.as_view(), name="detail"),
    path("<uuid:submission_id>/media", views.SubmissionMediaView.as_view(), name="media"),
    path("<uuid:submission_id>/finalize", views.SubmissionFinalizeView.as_view(), name="finalize"),
    path("<uuid:submission_id>/history", views.SubmissionHistoryView.as_view(), name="history"),
    path("<uuid:submission_id>/eligibility", views.SubmissionEligibilityView.as_view(), name="eligibility"),
    path("<uuid:submission_id>/tracks", views.SubmissionTrackView.as_view(), name="submission-tracks"),
]