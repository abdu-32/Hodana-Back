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
import urllib.parse
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

from . import oauth as oauth_adapters
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


import logging

logger = logging.getLogger(__name__)


def _send_mail(*, subject, message, to):
    """Single seam to swap for a Celery task later. Synchronous for now."""
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=[to],
            fail_silently=False,
        )
    except Exception as exc:
        logger.error("Failed to send email to %s: %s", to, exc)


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
    encoded_token = urllib.parse.quote(token)
    verify_url = f"{settings.FRONTEND_URL.rstrip('/')}/en/verify-email?token={encoded_token}"
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
    encoded_token = urllib.parse.quote(token)
    reset_url = f"{settings.FRONTEND_URL.rstrip('/')}/en/reset-password?token={encoded_token}"
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

PROFILE_UPDATE_FIELDS = [
    "full_name", "bio", "university", "skills", "avatar_url", "portfolio_url",
    "contact_email", "date_of_birth", "country",
]

# FR-HACK-003's age_restriction is enforced against this in
# registrations/services.py -- this floor is a separate, always-on
# platform-wide sanity check on the field itself, not a substitute for
# any specific hackathon's own age rule.
MIN_ACCOUNT_AGE_YEARS = 13
MAX_REASONABLE_AGE_YEARS = 120


def _validate_date_of_birth(value):
    if value is None:
        return value
    today = timezone.now().date()
    if value > today:
        raise ValidationError({"dateOfBirth": "Date of birth cannot be in the future."})
    age_years = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
    if age_years < MIN_ACCOUNT_AGE_YEARS:
        raise ValidationError({
            "dateOfBirth": f"You must be at least {MIN_ACCOUNT_AGE_YEARS} years old to use Innovation Hub."
        })
    if age_years > MAX_REASONABLE_AGE_YEARS:
        raise ValidationError({"dateOfBirth": "Please enter a valid date of birth."})
    return value


def _validate_country(value):
    """ISO 3166-1 alpha-2 only (e.g. "ET") -- matches the shape
    registrations/services.py expects when checking a hackathon's
    geographic_restriction.allowed_countries."""
    if not value:
        return value
    value = value.strip().upper()
    if len(value) != 2 or not value.isalpha():
        raise ValidationError({"country": "Country must be a 2-letter ISO 3166-1 code, e.g. 'ET'."})
    return value


def update_profile(*, account, data):
    """`account` is always the requester -- the view resolves 401/403
    before calling this."""
    data = dict(data)
    if "date_of_birth" in data:
        data["date_of_birth"] = _validate_date_of_birth(data["date_of_birth"])
    if "country" in data:
        data["country"] = _validate_country(data["country"])

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


# ---- FR-AUTH-005: OAuth sign-in (GitHub / Google) --------------------------

def oauth_login(*, provider, code, redirect_uri):
    """Exchanges an authorization code for the provider's own token
    server-side (the client secret never touches the frontend -- see
    accounts/oauth.py), then resolves it to an Account in one of three ways:

      1. An existing (oauth_provider, oauth_subject) match -> log them in.
      2. No identity match, but an existing Account with the same email,
         AND the provider marks that email `email_verified` -> link this
         OAuth identity to that account and log them in. An email the
         provider does NOT vouch for is never used for this match --
         trusting an unverified claim would let someone take over (or
         silently register against) somebody else's inbox just by typing
         it into their GitHub/Google profile.
      3. Neither -> create a brand-new Account, already verified (the
         provider vouching for the email substitutes for FR-AUTH-003's
         normal click-through step), with an unusable password.

    Returns (account, tokens, created).

    Known simplification: Account.oauth_provider/oauth_subject is a single
    pair per row, not a list, so an account can have at most one *linked*
    provider at a time. Logging in via a second provider with the same
    verified email still succeeds (case 2's `elif` below), but the second
    provider's identity is intentionally not written over the first --
    doing so would silently break the original provider's ability to
    match this account on its next login. Multiple simultaneously linked
    identities per account would need a separate join table; flagging
    that as a deliberate scope cut for this MVP, not an oversight.
    """
    provider_choices = dict(Account._meta.get_field("oauth_provider").choices)
    if provider not in provider_choices:
        raise ValidationError({"provider": "Unsupported OAuth provider."})

    profile = oauth_adapters.exchange_code_for_profile(
        provider=provider, code=code, redirect_uri=redirect_uri,
    )
    email = profile["email"].strip().lower()

    account = Account.objects.filter(oauth_provider=provider, oauth_subject=profile["subject"]).first()
    created = False

    if account is None:
        existing = Account.objects.filter(email__iexact=email).first()

        if existing is not None and profile["email_verified"]:
            account = existing
            if not account.oauth_provider:
                account.oauth_provider = provider
                account.oauth_subject = profile["subject"]
                account.save(update_fields=["oauth_provider", "oauth_subject", "updated_at"])
                AuditLogEntry.objects.create(
                    actor_id=account.id, action="account.oauth_linked",
                    target_type="account", target_id=str(account.id),
                    metadata={"provider": provider},
                )
            # else: already linked to a different provider -- log in via
            # the verified email match without disturbing that link.

        elif existing is not None:
            # Matching email exists, but this provider won't vouch for it.
            raise ValidationError({
                "email": "An account with this email already exists. Log in with your password, or "
                         f"verify this email address with {provider} first."
            })

        elif not profile["email_verified"]:
            raise ValidationError({
                "email": f"Your {provider} email address is not verified. Please verify it with "
                         f"{provider} first, or sign up with a password instead."
            })

        else:
            with transaction.atomic():
                account = Account.objects.create_user(
                    email=email, password=None,
                    full_name=profile["full_name"] or email.split("@", 1)[0],
                )
                account.set_unusable_password()
                account.oauth_provider = provider
                account.oauth_subject = profile["subject"]
                account.verification_status = "verified"
                account.email_verified_at = timezone.now()
                if profile.get("avatar_url"):
                    account.avatar_url = profile["avatar_url"]
                account.save()
                AuditLogEntry.objects.create(
                    actor_id=account.id, action="account.registered_via_oauth",
                    target_type="account", target_id=str(account.id),
                    metadata={"provider": provider},
                )
            created = True

    if not account.is_active:  # suspended or soft-deleted
        raise AuthenticationFailed(GENERIC_AUTH_ERROR)

    account.last_login_at = timezone.now()
    account.save(update_fields=["last_login_at", "updated_at"])

    if not created:
        AuditLogEntry.objects.create(
            actor_id=account.id, action="account.oauth_login",
            target_type="account", target_id=str(account.id),
            metadata={"provider": provider},
        )

    return account, _issue_tokens(account), created