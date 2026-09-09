"""
Mounted at api/v1/organizations/ in config/urls.py, so every path below
is relative to that prefix.
"""

from django.urls import path

from . import views

app_name = "organizations"

urlpatterns = [
    path("", views.OrganizationListCreateView.as_view(), name="list-create"),
    path("mine", views.OrganizationMineView.as_view(), name="mine"),
    path("<uuid:id>", views.OrganizationDetailView.as_view(), name="detail"),
    path(
        "<uuid:id>/verification-documents",
        views.OrganizationVerificationDocumentsView.as_view(),
        name="verification-documents",
    ),
    path(
        "<uuid:id>/verification-review",
        views.OrganizationVerificationReviewView.as_view(),
        name="verification-review",
    ),
]