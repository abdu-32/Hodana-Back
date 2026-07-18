"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import serializers, services


class HackathonRegistrationView(APIView):
    """POST /registrations/hackathons/{hackathon_id} -- FR-REG-001.
    Not yet in Doc 04 (which only sketches /hackathons/{id}/register under
    the Hackathons tag) -- this app owns its own url prefix per
    config/urls.py, so the real path lives here; add it to Doc 04/
    contracts/openapi.yaml once regenerated."""

    @extend_schema(
        request=serializers.RegisterForHackathonSerializer,
        responses={201: serializers.RegistrationSerializer},
    )
    def post(self, request, hackathon_id):
        serializer = serializers.RegisterForHackathonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        registration = services.register_for_hackathon(
            actor=request.user, hackathon_id=hackathon_id, **serializer.validated_data,
        )
        body = serializers.RegistrationSerializer(registration).data
        return Response(body, status=status.HTTP_201_CREATED)


class HackathonRegistrationWithdrawView(APIView):
    """POST /registrations/hackathons/{hackathon_id}/withdraw -- FR-REG-002."""

    @extend_schema(
            request=None,
            responses={200: serializers.RegistrationSerializer})
    def post(self, request, hackathon_id):
        registration = services.withdraw_registration(actor=request.user, hackathon_id=hackathon_id)
        return Response(serializers.RegistrationSerializer(registration).data)


class MyRegistrationsView(APIView):
    """GET /registrations/me -- FR-REG-003. Strictly scoped to the
    requester (services.list_my_registrations filters by actor)."""

    @extend_schema(responses={200: serializers.RegistrationSerializer(many=True)})
    def get(self, request):
        registrations = list(services.list_my_registrations(actor=request.user))
        body = {
            "data": serializers.RegistrationSerializer(registrations, many=True).data,
            "meta": {"limit": len(registrations), "offset": 0, "total": len(registrations)},
        }
        return Response(body)