"""
Mounted at api/v1/notifications/ in config/urls.py, so every path below
is relative to that prefix.
"""

from django.urls import path

from . import views

app_name = "notifications"

urlpatterns = [
    path("", views.NotificationCreateView.as_view(), name="create"),
    path("me", views.MyNotificationsView.as_view(), name="my-notifications"),
    path("me/<uuid:delivery_id>/read", views.NotificationMarkReadView.as_view(), name="mark-read"),
]
