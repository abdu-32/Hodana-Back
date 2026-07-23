"""Mounted at api/v1/showcase/ in config/urls.py."""
from django.urls import path

from . import views

app_name = "showcase"

urlpatterns = [
    path("gallery", views.ShowcaseGalleryView.as_view(), name="gallery"),
    path("hackathons/<uuid:hackathon_id>", views.HackathonShowcaseView.as_view(), name="hackathon-showcase"),
    path("hackathons/<uuid:hackathon_id>/publish", views.HackathonShowcasePublishView.as_view(), name="publish"),
    path("hackathons/<uuid:hackathon_id>/unpublish", views.HackathonShowcaseUnpublishView.as_view(), name="unpublish"),
    path("submissions/<uuid:submission_id>/visibility", views.SubmissionShowcaseVisibilityView.as_view(), name="submission-visibility"),
]