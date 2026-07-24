"""
Mounted at api/v1/analytics/ in config/urls.py, so every path below is
relative to that prefix.
"""

from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path(
        "hackathons/<uuid:hackathon_id>/dashboard",
        views.RegistrationDashboardView.as_view(),
        name="dashboard",
    ),
    path(
        "hackathons/<uuid:hackathon_id>/demographics",
        views.DemographicBreakdownView.as_view(),
        name="demographics",
    ),
]
