"""
Mounted at api/v1/registrations/ in config/urls.py, so every path below
is relative to that prefix.
"""

from django.urls import path

from . import views

app_name = "registrations"

urlpatterns = [
    path(
        "hackathons/<str:hackathon_id>",
        views.HackathonRegistrationView.as_view(),
        name="register",
    ),
    path(
        "hackathons/<str:hackathon_id>/withdraw",
        views.HackathonRegistrationWithdrawView.as_view(),
        name="withdraw",
    ),
    path(
        "hackathons/<str:hackathon_id>/type",
        views.HackathonRegistrationTypeView.as_view(),
        name="update-type",
    ),
    path("me", views.MyRegistrationsView.as_view(), name="my-registrations"),
    path("organizer", views.OrganizerRegistrationsView.as_view(), name="organizer-registrations"),
]