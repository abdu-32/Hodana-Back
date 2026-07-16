"""
HTTP concerns only: routing to a service call, permission checks, and
response status codes. No business logic here (Design Spec Sec 3.1).
"""

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from . import serializers, services

from apps.core.throttling import FiveMinuteScopedRateThrottle

#    --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


class SignupView(APIView):
    """POST /auth/signup -- FR-AUTH-001."""

    permission_classes = [AllowAny]

    @extend_schema(
        request=serializers.SignupSerializer,
        responses={201: serializers.UserProfileSerializer},
    )
    def post(self, request):
        serializer = serializers.SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        account = services.register_account(
            email=data["email"],
            password=data["password"],
            full_name=data.get("full_name", ""),
        )
        # Deliberately NOT issuing tokens here, even though Doc 04's
        # AuthResponse implies signup returns access/refresh tokens:
        # FR-AUTH-001 says the account "cannot log in until FR-AUTH-003
        # completes", so handing back a usable session for an unverified
        # account would contradict that. Flagging this as a contract
        # mismatch to resolve in Doc 04, not silently issuing a session.
        body = serializers.UserProfileSerializer(account).data
        return Response(body, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    """POST /auth/login -- FR-AUTH-002."""

    permission_classes = [AllowAny]

    @extend_schema(
        request=serializers.LoginSerializer,
        responses={200: serializers.AuthResponseSerializer},
    )
    def post(self, request):
        serializer = serializers.LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account, tokens = services.authenticate_and_issue_tokens(**serializer.validated_data)
        body = serializers.AuthResponseSerializer({**tokens, "user": account}).data
        return Response(body, status=status.HTTP_200_OK)


class RefreshView(APIView):
    """POST /auth/refresh -- FR-AUTH-002. Replaces SimpleJWT's stock
    TokenRefreshView: that view neither matches the contract's response
    shape nor checks token_version on the refresh token itself (see
    services.refresh_access_token's docstring)."""

    permission_classes = [AllowAny]


    @extend_schema(
        request=serializers.RefreshSerializer,
        responses={200: serializers.AuthResponseSerializer},
    )
    def post(self, request):
        serializer = serializers.RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account, tokens = services.refresh_access_token(
            refresh_token=serializer.validated_data["refresh_token"]
        )
        body = serializers.AuthResponseSerializer({**tokens, "user": account}).data
        return Response(body, status=status.HTTP_200_OK)


class VerifyEmailView(APIView):
    """POST /auth/verify-email -- FR-AUTH-003. Not yet in Doc 04; add it."""

    permission_classes = [AllowAny]


    @extend_schema(
        request=serializers.VerifyEmailSerializer,
        responses={200: serializers.UserProfileSerializer},
    )
    def post(self, request):
        serializer = serializers.VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = services.verify_email(token=serializer.validated_data["token"])
        return Response(serializers.UserProfileSerializer(account).data, status=status.HTTP_200_OK)


class ResendVerificationView(APIView):
    """POST /auth/verify-email/resend -- FR-AUTH-003 (1 request / 5 min).
    Not yet in Doc 04; add it."""

    permission_classes = [AllowAny]
    throttle_classes = [FiveMinuteScopedRateThrottle]
    throttle_scope = "email_verification_resend"


    @extend_schema(
        request=serializers.ResendVerificationSerializer,
        responses={202: None},
    )
    def post(self, request):
        serializer = serializers.ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.resend_verification_email(email=serializer.validated_data["email"])
        # Always 202, regardless of whether the email exists or is already
        # verified -- same non-enumeration reasoning as BR-012.
        return Response(status=status.HTTP_202_ACCEPTED)


class PasswordResetRequestView(APIView):
    """POST /auth/password-reset -- FR-AUTH-004. Not yet in Doc 04; add it."""

    permission_classes = [AllowAny]


    @extend_schema(
        request=serializers.PasswordResetRequestSerializer,
        responses={200: inline_serializer(
            name="PasswordResetRequestResponse",
            fields={"message": drf_serializers.CharField()},
        )},
    )
    def post(self, request):
        serializer = serializers.PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = services.request_password_reset(email=serializer.validated_data["email"])
        return Response({"message": message}, status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    """POST /auth/password-reset/confirm -- FR-AUTH-004. Not yet in Doc 04;
    add it."""

    permission_classes = [AllowAny]

    @extend_schema(
        request=serializers.PasswordResetConfirmSerializer,
        responses={200: None},
    )
    def post(self, request):
        serializer = serializers.PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reset_password(
            token=serializer.validated_data["token"],
            new_password=serializer.validated_data["new_password"],
        )
        return Response(status=status.HTTP_200_OK)


# --------------------------------------------------------------------------
# Users / profile
# --------------------------------------------------------------------------


class CurrentUserView(APIView):
    """GET/PUT /users/me -- FR-PROFILE-001. No explicit permission_classes:
    the project default (IsAuthenticated) already gives an unauthenticated
    request a 401 with no extra code needed here."""


    @extend_schema(responses={200: serializers.UserProfileSerializer})
    def get(self, request):
        return Response(serializers.UserProfileSerializer(request.user).data)
    
    @extend_schema(
        request=serializers.UserUpdateSerializer,
        responses={200: serializers.UserProfileSerializer},
    )
    def put(self, request):
        serializer = serializers.UserUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = services.update_profile(account=request.user, data=serializer.validated_data)
        return Response(serializers.UserProfileSerializer(account).data)


class UserPublicProfileView(APIView):
    """GET /users/{id} -- FR-PROFILE-002: "reachable without
    authentication". Doc 04 doesn't mark this operation `security: []`
    the way it does for /auth/* -- treating the FR as authoritative and
    flagging the contract as needing that override added."""

    permission_classes = [AllowAny]
    
    @extend_schema(responses={200: serializers.PublicProfileSerializer})
    def get(self, request, id):
        account = services.get_public_profile(account_id=id)
        return Response(serializers.PublicProfileSerializer(account).data)