"""
Mounted at api/v1/registrations/ in config/urls.py, so every path below
is relative to that prefix.
"""

from django.urls import path

from . import views

app_name = "registrations"

urlpatterns = [
    path(
        "hackathons/<uuid:hackathon_id>",
        views.HackathonRegistrationView.as_view(),
        name="register",
    ),
    path(
        "hackathons/<uuid:hackathon_id>/withdraw",
        views.HackathonRegistrationWithdrawView.as_view(),
        name="withdraw",
    ),
    path("me", views.MyRegistrationsView.as_view(), name="my-registrations"),
]