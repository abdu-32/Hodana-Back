"""
Mounted at api/v1/submissions/ in config/urls.py, so every path below is
relative to that prefix.
"""

from django.urls import path

from . import views

app_name = "submissions"

urlpatterns = [
    path("mine", views.MySubmissionsListView.as_view(), name="my-submissions"),
    path("organizer", views.OrganizerSubmissionsListView.as_view(), name="organizer-submissions"),
    path("organizer/winner", views.OrganizerAssignWinnerView.as_view(), name="organizer-assign-winner"),
    path("organizer/request-payout", views.OrganizerRequestPayoutView.as_view(), name="organizer-request-payout"),
    path("organizer/request-top-3-payouts", views.OrganizerRequestTop3PayoutView.as_view(), name="organizer-request-top-3-payouts"),
    path("organizer/mark-payout-paid", views.OrganizerMarkPayoutPaidView.as_view(), name="organizer-mark-payout-paid"),
    path("hackathons/<str:hackathon_id>", views.SubmissionUpsertView.as_view(), name="upsert"),
    path("hackathons/<str:hackathon_id>/me", views.MyHackathonSubmissionView.as_view(), name="my-submission"),

    path("<uuid:submission_id>", views.SubmissionDetailView.as_view(), name="detail"),
    path("<uuid:submission_id>/media", views.SubmissionMediaView.as_view(), name="media"),
    path("<uuid:submission_id>/finalize", views.SubmissionFinalizeView.as_view(), name="finalize"),
    path("<uuid:submission_id>/history", views.SubmissionHistoryView.as_view(), name="history"),
    path("<uuid:submission_id>/eligibility", views.SubmissionEligibilityView.as_view(), name="eligibility"),
    path("<uuid:submission_id>/tracks", views.SubmissionTrackView.as_view(), name="submission-tracks"),
    path("<uuid:submission_id>/payout-details", views.ParticipantSubmitPayoutDetailsView.as_view(), name="submission-payout-details"),
]