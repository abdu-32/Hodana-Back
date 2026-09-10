from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from . import services
from .serializers import (
    TicketSerializer, TicketDetailSerializer, TicketCreateSerializer,
    TicketMessageSerializer, TicketMessageCreateSerializer,
    InternalNoteSerializer, InternalNoteCreateSerializer,
    AttachmentSerializer, AttachmentCreateSerializer,
    AssignmentSerializer, AssignTicketSerializer,
    StatusUpdateSerializer, PaginatedTicketsSerializer
)

class TicketListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = int(request.query_params.get("limit", 20))
        offset = int(request.query_params.get("offset", 0))
        status_filter = request.query_params.get("status")
        tickets, total = services.list_my_tickets(actor=request.user, status=status_filter, limit=limit, offset=offset)
        return Response({
            "data": TicketSerializer(tickets, many=True).data,
            "meta": {"limit": limit, "offset": offset, "total": total}
        })

    def post(self, request):
        serializer = TicketCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ticket = services.create_ticket(
            actor=request.user,
            subject=data["subject"],
            body=data["body"],
            category=data["category"],
            priority=data.get("priority", "normal"),
            scope_type=data.get("scopeType") or data.get("scope_type"),
            scope_id=data.get("scopeId") or data.get("scope_id"),
            other_details=data.get("otherDetails") or data.get("details"),
        )
        return Response(TicketSerializer(ticket).data, status=status.HTTP_201_CREATED)


class TicketDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        ticket = services.get_ticket(actor=request.user, ticket_id=id)
        return Response(TicketDetailSerializer(ticket).data)

class TicketMessageListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        messages = services.list_ticket_messages(actor=request.user, ticket_id=id)
        return Response(TicketMessageSerializer(messages, many=True).data)

    def post(self, request, id):
        serializer = TicketMessageCreateSerializer(data={"ticketId": id, **request.data})
        serializer.is_valid(raise_exception=True)
        message = services.add_message(
            actor=request.user,
            ticket_id=serializer.validated_data["ticketId"],
            body=serializer.validated_data["body"]
        )
        return Response(TicketMessageSerializer(message).data, status=status.HTTP_201_CREATED)

class TicketStatusUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, id):
        serializer = StatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = services.update_ticket_status(
            actor=request.user,
            ticket_id=id,
            new_status=serializer.validated_data["status"]
        )
        return Response(TicketSerializer(ticket).data)

class AttachmentCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AttachmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attachment = services.add_attachment(
            actor=request.user,
            ticket_id=serializer.validated_data["ticketId"],
            message_id=serializer.validated_data.get("messageId"),
            file_url=serializer.validated_data["fileUrl"],
            filename=serializer.validated_data["filename"],
            file_size=serializer.validated_data["fileSize"],
            content_type=serializer.validated_data["contentType"]
        )
        return Response(AttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)

class StaffTicketListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        limit = int(request.query_params.get("limit", 20))
        offset = int(request.query_params.get("offset", 0))
        status_filter = request.query_params.get("status")
        priority = request.query_params.get("priority")
        assignee_id = request.query_params.get("assignee_id")
        
        tickets, total = services.list_staff_tickets(
            actor=request.user, status=status_filter, priority=priority,
            assignee_id=assignee_id, limit=limit, offset=offset
        )
        return Response({
            "data": TicketSerializer(tickets, many=True).data,
            "meta": {"limit": limit, "offset": offset, "total": total}
        })

class InternalNoteCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = InternalNoteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = services.add_internal_note(
            actor=request.user,
            ticket_id=serializer.validated_data["ticketId"],
            body=serializer.validated_data["body"]
        )
        return Response(InternalNoteSerializer(note).data, status=status.HTTP_201_CREATED)

class InternalNoteListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, ticket_id):
        notes = services.list_internal_notes(actor=request.user, ticket_id=ticket_id)
        return Response(InternalNoteSerializer(notes, many=True).data)

class TicketAssignView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AssignTicketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        assignment = services.assign_ticket(
            actor=request.user,
            ticket_id=serializer.validated_data["ticketId"],
            assignee_id=serializer.validated_data["assigneeId"]
        )
        return Response(AssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)
