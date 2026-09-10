"""
Mounted at api/v1/ (not api/v1/auth/) in config/urls.py, since this app
owns both the Auth and Users tags from Doc 04 -- the auth/ and users/
prefixes below are what actually produce api/v1/auth/... and
api/v1/users/... .
"""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("auth/signup", views.SignupView.as_view(), name="signup"),
    path("auth/signup/", views.SignupView.as_view(), name="signup-slash"),
    path("auth/login", views.LoginView.as_view(), name="login"),
    path("auth/login/", views.LoginView.as_view(), name="login-slash"),
    path("auth/oauth/<str:provider>/login", views.OAuthLoginView.as_view(), name="oauth-login"),
    path("auth/oauth/<str:provider>/login/", views.OAuthLoginView.as_view(), name="oauth-login-slash"),
    path("auth/refresh", views.RefreshView.as_view(), name="refresh"),
    path("auth/refresh/", views.RefreshView.as_view(), name="refresh-slash"),
    path("auth/verify-email", views.VerifyEmailView.as_view(), name="verify-email"),
    path("auth/verify-email/", views.VerifyEmailView.as_view(), name="verify-email-slash"),
    path(
        "auth/verify-email/resend",
        views.ResendVerificationView.as_view(),
        name="resend-verification",
    ),
    path(
        "auth/verify-email/resend/",
        views.ResendVerificationView.as_view(),
        name="resend-verification-slash",
    ),
    path(
        "auth/password-reset",
        views.PasswordResetRequestView.as_view(),
        name="password-reset-request",
    ),
    path(
        "auth/password-reset/",
        views.PasswordResetRequestView.as_view(),
        name="password-reset-request-slash",
    ),
    path(
        "auth/password-reset/confirm",
        views.PasswordResetConfirmView.as_view(),
        name="password-reset-confirm",
    ),
    path(
        "auth/password-reset/confirm/",
        views.PasswordResetConfirmView.as_view(),
        name="password-reset-confirm-slash",
    ),
    path("users/me", views.CurrentUserView.as_view(), name="current-user"),
    path("users/me/", views.CurrentUserView.as_view(), name="current-user-slash"),
    path("users/<uuid:id>", views.UserPublicProfileView.as_view(), name="public-profile"),
    path("users/<uuid:id>/", views.UserPublicProfileView.as_view(), name="public-profile-slash"),
]