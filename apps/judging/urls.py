"""Mounted at api/v1/judging/ in config/urls.py."""
from django.urls import path
from . import views

app_name = "judging"

urlpatterns = [
    path("rounds", views.JudgingRoundListCreateView.as_view(), name="rounds"),
    path("rounds/<uuid:round_id>/criteria", views.JudgingCriterionListCreateView.as_view(), name="criteria"),
    path("rounds/<uuid:round_id>/assignments", views.AssignmentListCreateView.as_view(), name="assignments"),
    path("rounds/<uuid:round_id>/assignments/auto", views.AutoDistributionView.as_view(), name="auto-assignments"),
    path("assignments/<uuid:assignment_id>", views.AssignmentDeleteView.as_view(), name="remove-assignment"),
    path("assignments/<uuid:assignment_id>/reassign", views.AssignmentReassignView.as_view(), name="reassign-assignment"),
    path("rounds/<uuid:round_id>/open", views.RoundOpenView.as_view(), name="open-round"),
    path("rounds/<uuid:round_id>/close", views.RoundCloseView.as_view(), name="close-round"),
    path("rounds/<uuid:round_id>/results", views.RoundResultListView.as_view(), name="results"),
    path("judge/invitations", views.JudgeInvitationCreateView.as_view(), name="invite"),
    path("judge/invitations/<uuid:invitation_id>", views.JudgeInvitationDetailView.as_view(), name="invitation-detail"),
    path("judge/invitations/<uuid:invitation_id>/accept", views.JudgeInvitationAcceptView.as_view(), name="accept-invitation"),
    path("judge/invitations/<uuid:invitation_id>/decline", views.JudgeInvitationDeclineView.as_view(), name="decline-invitation"),
    path("judge/invitations/<uuid:invitation_id>/revoke", views.JudgeInvitationRevokeView.as_view(), name="revoke-invitation"),
    path("organizer/judges", views.OrganizerJudgeListView.as_view(), name="organizer-judges"),
    path("assigned-hackathons", views.JudgeAssignedHackathonListView.as_view(), name="assigned-hackathons"),
    path("hackathons/<str:hackathon_id>/submissions", views.JudgeSubmissionListView.as_view(), name="hackathon-submissions"),
    path("submissions/<uuid:submission_id>/evaluate", views.JudgeSubmissionEvaluateView.as_view(), name="evaluate-submission"),
    path("submissions/<uuid:submission_id>/scores", views.SubmissionScoreListView.as_view(), name="submission-scores"),
    path("submissions/<uuid:submission_id>/score", views.SubmissionScoreCreateView.as_view(), name="submit-score"),
    path("scores/<uuid:score_id>/reopen", views.ScoreReopenView.as_view(), name="reopen-score"),
]
