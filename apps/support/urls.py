from django.urls import path
from . import views

urlpatterns = [
    path("tickets/", views.TicketListCreateView.as_view()),
    path("tickets/<uuid:id>/", views.TicketDetailView.as_view()),
    path("tickets/<uuid:id>/messages/", views.TicketMessageListCreateView.as_view()),
    path("tickets/<uuid:id>/status/", views.TicketStatusUpdateView.as_view()),
    path("attachments/", views.AttachmentCreateView.as_view()),
    path("staff/tickets/", views.StaffTicketListView.as_view()),
    path("staff/notes/", views.InternalNoteCreateView.as_view()),
    path("staff/notes/<uuid:ticket_id>/", views.InternalNoteListView.as_view()),
    path("staff/assign/", views.TicketAssignView.as_view()),
]
