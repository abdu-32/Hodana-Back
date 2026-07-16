"""
accounts -- services

Per Design Spec Sec 3.1: all business logic and cross-model orchestration
lives here. This is the layer that enforces the business rules from
Document 02 Sec 4 and is unit-tested directly (NFR-MAINT-001: 80% coverage
target) without spinning up HTTP requests.
"""

"""
accounts -- services
...
"""

import re
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password
from rest_framework.exceptions import APIException, AuthenticationFailed, NotFound, ValidationError
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from apps.core.models import AuditLogEntry

from .models import Account


class ConflictError(APIException):
    """HTTP 409 -- used only where BR-012 requires *not* revealing why."""
    status_code = 409
    default_detail = "Unable to complete this request."
    default_code = "conflict"


PASSWORD_MIN_LENGTH = 10

LOCKOUT_THRESHOLD = 5  # FR-AUTH-002
LOCKOUT_WINDOW = timedelta(minutes=15)
LOCKOUT_DURATION = timedelta(minutes=15)

EMAIL_VERIFICATION_SALT = "accounts.email-verification"
EMAIL_VERIFICATION_MAX_AGE = 24 * 60 * 60  # 24h, FR-AUTH-003

PASSWORD_RESET_SALT = "accounts.password-reset"
PASSWORD_RESET_MAX_AGE = 60 * 60  # 1h, FR-AUTH-004

GENERIC_AUTH_ERROR = "Invalid email or password."
GENERIC_RESET_MESSAGE = "If an account exists for this email, a password reset link has been sent."


def _send_mail(*, subject, message, to):
    """Single seam to swap for a Celery task later. Synchronous for now."""
    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[to],
        fail_silently=False,
    )


def _validate_password_strength(password, account=None):
    """FR-AUTH-001 / FR-AUTH-004: at least 10 chars, >=1 letter, >=1 digit,
    plus Django's own AUTH_PASSWORD_VALIDATORS (CommonPasswordValidator,
    UserAttributeSimilarityValidator, etc. -- config/settings/base.py).
    The latter were configured but never actually invoked anywhere in the
    registration/reset flow; wiring them in here closes that gap.

    `account` is passed through to Django's validators as `user=` so
    UserAttributeSimilarityValidator can compare against email/full_name;
    at registration time no row exists yet, so callers pass an unsaved
    Account(email=..., full_name=...) instead.
    """
    if (
        len(password) < PASSWORD_MIN_LENGTH
        or not re.search(r"[A-Za-z]", password)
        or not re.search(r"\d", password)
    ):
        raise ValidationError({
            "password": "Password must be at least 10 characters and include at least one letter and one number."
        })
    try:
        validate_password(password, user=account)
    except DjangoValidationError as exc:
        raise ValidationError({"password": exc.messages})


def _issue_tokens(account):
    """FR-AUTH-002. Embeds token_version so TokenVersionJWTAuthentication
    (Design Spec Sec 4.3) can reject tokens after reset/logout-all/suspend."""
    refresh = RefreshToken.for_user(account)
    refresh["token_version"] = account.token_version
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


# ---- FR-AUTH-001: registration -------------------------------------------

def register_account(*, email, password, full_name):
    """Note: SignupRequest (Doc 04) has no role field, so the SRS's
    "select Participant or Organizer" isn't persisted here -- Organizer
    status comes from RoleAssignment when they create an org (FR-ORG-001)."""
    email = email.strip().lower()
    _validate_password_strength(password, account=Account(email=email, full_name=full_name))

    if Account.objects.filter(email__iexact=email).exists():
        raise ConflictError("Unable to create an account with the provided details.")  # BR-012

    with transaction.atomic():
        account = Account.objects.create_user(email=email, password=password, full_name=full_name)
        AuditLogEntry.objects.create(
            actor_id=account.id, action="account.registered",
            target_type="account", target_id=str(account.id),
        )

    send_verification_email(account)
    return account


# ---- FR-AUTH-003: email verification --------------------------------------

def _make_verification_token(account):
    return signing.dumps({"uid": str(account.id)}, salt=EMAIL_VERIFICATION_SALT)


def send_verification_email(account):
    token = _make_verification_token(account)
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    _send_mail(
        subject="Verify your Innovation Hub account",
        message=f"Confirm your email address to activate your account:\n\n{verify_url}",
        to=account.email,
    )
    return token


def resend_verification_email(*, email):
    """Rate limiting (1/5min) belongs at the view layer via ScopedRateThrottle.
    No-ops silently for unknown/already-verified email (don't reveal state)."""
    try:
        account = Account.objects.get(email__iexact=email.strip().lower())
    except Account.DoesNotExist:
        return
    if account.verification_status == "verified":
        return
    send_verification_email(account)


def verify_email(*, token):
    try:
        payload = signing.loads(token, salt=EMAIL_VERIFICATION_SALT, max_age=EMAIL_VERIFICATION_MAX_AGE)
    except signing.SignatureExpired:
        raise ValidationError({"token": "This verification link has expired."})
    except signing.BadSignature:
        raise ValidationError({"token": "This verification link is invalid."})

    try:
        account = Account.objects.get(id=payload["uid"])
    except Account.DoesNotExist:
        raise ValidationError({"token": "This verification link is invalid."})

    if account.verification_status != "verified":
        account.verification_status = "verified"
        account.email_verified_at = timezone.now()
        account.save(update_fields=["verification_status", "email_verified_at", "updated_at"])
    return account


# ---- FR-AUTH-002: login ----------------------------------------------------

def _register_failed_login(account):
    now = timezone.now()
    # No dedicated "first failed attempt at" field exists, so `updated_at`
    # approximates a rolling 15-minute window.
    if account.updated_at and (now - account.updated_at) > LOCKOUT_WINDOW:
        account.failed_login_count = 0

    account.failed_login_count += 1

    if account.failed_login_count >= LOCKOUT_THRESHOLD:
        account.lock_until = now + LOCKOUT_DURATION
        account.failed_login_count = 0
        _send_mail(
            subject="Your account has been temporarily locked",
            message="We locked your account for 15 minutes after several failed login attempts. If this wasn't you, consider resetting your password.",
            to=account.email,
        )

    account.save(update_fields=["failed_login_count", "lock_until", "updated_at"])


def authenticate_and_issue_tokens(*, email, password):
    email = email.strip().lower()

    try:
        account = Account.objects.get(email__iexact=email)
    except Account.DoesNotExist:
        raise AuthenticationFailed(GENERIC_AUTH_ERROR)

    if account.lock_until and account.lock_until > timezone.now():
        raise AuthenticationFailed("Account temporarily locked. Please try again later.")

    if not account.check_password(password):
        _register_failed_login(account)
        raise AuthenticationFailed(GENERIC_AUTH_ERROR)

    if account.verification_status != "verified":
        raise AuthenticationFailed("Please verify your email before logging in.")

    if not account.is_active:  # suspended or soft-deleted
        raise AuthenticationFailed(GENERIC_AUTH_ERROR)

    account.failed_login_count = 0
    account.lock_until = None
    account.last_login_at = timezone.now()
    account.save(update_fields=["failed_login_count", "lock_until", "last_login_at", "updated_at"])

    return account, _issue_tokens(account)


# ---- FR-AUTH-004: password reset ------------------------------------------

def _make_reset_token(account):
    return signing.dumps({"uid": str(account.id), "pwd": account.password[-16:]}, salt=PASSWORD_RESET_SALT)


def request_password_reset(*, email):
    try:
        account = Account.objects.get(email__iexact=email.strip().lower())
    except Account.DoesNotExist:
        return GENERIC_RESET_MESSAGE

    token = _make_reset_token(account)
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
    _send_mail(
        subject="Reset your Innovation Hub password",
        message=f"Reset your password using this link (valid 1 hour):\n\n{reset_url}",
        to=account.email,
    )
    return GENERIC_RESET_MESSAGE


def reset_password(*, token, new_password):
    try:
        payload = signing.loads(token, salt=PASSWORD_RESET_SALT, max_age=PASSWORD_RESET_MAX_AGE)
    except signing.SignatureExpired:
        raise ValidationError({"token": "This reset link has expired."})
    except signing.BadSignature:
        raise ValidationError({"token": "This reset link is invalid."})

    try:
        account = Account.objects.get(id=payload["uid"])
    except Account.DoesNotExist:
        raise ValidationError({"token": "This reset link is invalid."})

    if account.password[-16:] != payload["pwd"]:
        raise ValidationError({"token": "This reset link has already been used."})

    _validate_password_strength(new_password, account=account)

    with transaction.atomic():
        account.set_password(new_password)
        account.token_version += 1  # NFR-SEC-005: invalidate all existing sessions
        account.failed_login_count = 0
        account.lock_until = None
        account.save(update_fields=["password", "token_version", "failed_login_count", "lock_until", "updated_at"])

    return account


# ---- FR-PROFILE-001: update own profile ------------------------------------

PROFILE_UPDATE_FIELDS = ["full_name", "bio", "university", "skills", "avatar_url", "portfolio_url", "contact_email"]


def update_profile(*, account, data):
    """`account` is always the requester -- the view resolves 401/403
    before calling this."""
    fields_to_update = []
    for field in PROFILE_UPDATE_FIELDS:
        if field in data:
            setattr(account, field, data[field])
            fields_to_update.append(field)
    if fields_to_update:
        account.save(update_fields=[*fields_to_update, "updated_at"])
    return account


# ---- FR-PROFILE-002: public profile ----------------------------------------

def get_public_profile(*, account_id):
    """Returns 404 (never 403) for private or non-existent, so existence
    can't be inferred."""
    try:
        account = Account.objects.get(id=account_id, deleted_at__isnull=True)
    except (Account.DoesNotExist, ValueError, ValidationError, DjangoValidationError):
        raise NotFound()

    if account.profile_visibility != "public":
        raise NotFound()

    return account


def refresh_access_token(*, refresh_token):
    """Implements the /auth/refresh leg of FR-AUTH-002.

    Rotation alone (ROTATE_REFRESH_TOKENS/BLACKLIST_AFTER_ROTATION in
    SIMPLE_JWT) isn't enough on its own: a *stolen* refresh token issued
    before a password reset must stop working the moment token_version
    bumps, same as an access token does. So the refresh token's own
    token_version claim is checked against the current DB value here,
    not just re-embedded into the new pair.
    """
    try:
        old_refresh = RefreshToken(refresh_token)
    except TokenError:
        raise AuthenticationFailed("Invalid or expired refresh token.")

    account_id = old_refresh.payload.get("user_id")
    token_version = old_refresh.payload.get("token_version")

    try:
        account = Account.objects.get(id=account_id)
    except (Account.DoesNotExist, ValueError, TypeError):
        raise AuthenticationFailed("Invalid or expired refresh token.")

    if token_version is None or token_version != account.token_version:
        raise AuthenticationFailed("Invalid or expired refresh token.")

    if not account.is_active:
        raise AuthenticationFailed("Invalid or expired refresh token.")

    try:
        old_refresh.blacklist()
    except AttributeError:
        pass  # token_blacklist app not installed -- rotate without blacklisting

    return account, _issue_tokens(account)