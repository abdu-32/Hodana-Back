"""
Base settings, shared by every environment (development / staging / production).

Per Design Spec Sec 8.2: environments share the same container image and differ
only by configuration and data — this file must never contain environment-
specific values. Those go in development.py / production.py, which import
from here and override/extend.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key-change-me")

# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",  # for JSONField, see Doc 08 Sec 3.2
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",
    "rest_framework_simplejwt.token_blacklist",
    "django_celery_beat",
    "django_celery_results",
    # Re-enable when moving off local filesystem storage (see README):
    # "storages",
]

# Module-to-requirement mapping — Design Spec Sec 3.2.
# Order matters only for admin display; dependency direction is enforced in
# services.py, not by app registration order.
LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.organizations",
    "apps.hackathons",
    "apps.registrations",
    "apps.teams",
    "apps.submissions",
    "apps.judging",
    "apps.showcase",
    "apps.notifications",
    "apps.analytics",
    "apps.platform_admin",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",  # I18N — Design Spec Sec 6.4
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_USER_MODEL = "accounts.Account"

# --------------------------------------------------------------------------
# Database — configured per-environment via DATABASE_URL (Sec 3.2, Doc 08)
# --------------------------------------------------------------------------

DATABASES = {
    "default": env.db("DATABASE_URL", default="sqlite:///db.sqlite3"),
}

# --------------------------------------------------------------------------
# Password validation
# --------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------------------------------
# I18N — bilingual UI per Design Spec Sec 6.4 (English / Amharic)
# --------------------------------------------------------------------------

LANGUAGE_CODE = "en"
LANGUAGES = [
    ("en", "English"),
    ("am", "Amharic"),
]
TIME_ZONE = "Africa/Addis_Ababa"
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static / media
# --------------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --------------------------------------------------------------------------
# DRF + JWT — Design Spec Sec 4.1 (stateless JWT, 15 min access / 30 day refresh)
# --------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "apps.accounts.authentication.TokenVersionJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "email_verification_resend": "1/5min",
        # IP-scoped (DRF falls back to request IP when there's no
        # authenticated user, which is always true for these endpoints).
        # Complements, doesn't replace, the per-account lockout in
        # accounts/services.py -- that stops repeated guesses against one
        # account; this stops a spray across many accounts, or scripted
        # mass signups, from one source. Rates are deliberately generous
        # enough not to lock out a shared campus/office NAT doing normal
        # traffic, while still capping automated abuse at a small multiple
        # of that instead of "unlimited".
        "login": "30/min",
        "signup": "10/hour",
        "oauth_login": "20/min",
        "password_reset_request": "10/hour",
    },
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# --------------------------------------------------------------------------
# drf-spectacular — this IS the contract. Regenerated from real views/
# serializers via `scripts/export_contract.sh`, never hand-edited.
# The frontend repo only ever sees the exported contracts/openapi.yaml file,
# not this running server.
# --------------------------------------------------------------------------

SPECTACULAR_SETTINGS = {
    "TITLE": "Ethiopia Innovation Hub API",
    "DESCRIPTION": "Hackathon and innovation-challenge platform API.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=["http://localhost:3000"])

# --------------------------------------------------------------------------
# Celery + Redis — Design Spec Sec 6.1-6.2. Re-enabled now that
# apps.notifications has periodic jobs to run: the 24h-before submission
# deadline reminder and the 90-day in-app notification purge (see
# apps/notifications/tasks.py and CELERY_BEAT_SCHEDULE below).
# --------------------------------------------------------------------------

from celery.schedules import crontab  # noqa: E402

REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = "django-db"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

CELERY_TASK_ROUTES = {
    "apps.notifications.*": {"queue": "notifications"},
    "apps.submissions.tasks.*": {"queue": "media"},
    "apps.analytics.tasks.*": {"queue": "analytics"},
    "apps.hackathons.tasks.*": {"queue": "scheduled"},
}

# FR-NOTIFY-001/002 (deadline reminder) and FR-NOTIFY-001 (90-day in-app
# retention) — the underlying service functions already existed and were
# already tested; this is the scheduler that was missing. Runs hourly
# rather than once/day so a hackathon whose submission_closes_at falls
# anywhere inside a given hour still gets its reminder within that same
# hour, without ever re-notifying the same hackathon twice (the task
# only matches hackathons whose deadline is 23-24h out — see
# apps.notifications.tasks.send_submission_deadline_reminders).
CELERY_BEAT_SCHEDULE = {
    "notifications-submission-deadline-reminders": {
        "task": "apps.notifications.tasks.send_submission_deadline_reminders",
        "schedule": crontab(minute=0),  # every hour, on the hour
    },
    "notifications-purge-expired-in-app": {
        "task": "apps.notifications.tasks.purge_expired_in_app_notifications_task",
        "schedule": crontab(hour=3, minute=0),  # once daily, 03:00 server time
    },
}

CACHES = {
    "default": {
        # LocMemCache here is fine for local dev/tests (typically a single
        # process). Production overrides this to a shared Redis backend --
        # see config/settings/production.py for why: DRF's ScopedRateThrottle
        # (used by the login/signup/etc. throttles below) stores its request
        # counters in this cache, and a per-process cache would let each
        # gunicorn/uvicorn worker enforce "the rate" independently,
        # silently multiplying every throttle limit by however many
        # workers are running.
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# --------------------------------------------------------------------------
# Object storage — DISABLED for now, using local filesystem instead.
# Re-enable S3 when you deploy beyond a single API replica (local disk
# doesn't survive horizontal scaling — see README). Until then, either
# run as-is (uploads live on local disk) or swap to a self-hosted MinIO
# container later without any code change (same S3 API).
# --------------------------------------------------------------------------

# STORAGES = {
#     "default": {"BACKEND": "storages.backends.s3.S3Storage"},
#     "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
# }

# AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME", default="")
# AWS_S3_ENDPOINT_URL = env("AWS_S3_ENDPOINT_URL", default="")
# AWS_ACCESS_KEY_ID = env("AWS_ACCESS_KEY_ID", default="")
# AWS_SECRET_ACCESS_KEY = env("AWS_SECRET_ACCESS_KEY", default="")

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:3000")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@innovationhub.local")

# --------------------------------------------------------------------------
# FR-AUTH-005 -- OAuth sign-in (GitHub, Google). Client secrets are
# server-side only: the frontend only ever sees the public client_id (to
# build the provider's own authorize URL) and the one-time `code` it gets
# back, which this backend then exchanges -- see apps/accounts/oauth.py.
# Get these from https://github.com/settings/developers (GitHub) and
# https://console.cloud.google.com/apis/credentials (Google); set the
# provider's "Authorization callback URL" to
# {FRONTEND_URL}/auth/oauth/{provider}/callback (or wherever the frontend
# route lives) with the exact host/scheme it will actually run on.
# --------------------------------------------------------------------------

OAUTH_PROVIDERS = {
    "github": {
        "client_id": env("GITHUB_CLIENT_ID", default=""),
        "client_secret": env("GITHUB_CLIENT_SECRET", default=""),
        "token_url": "https://github.com/login/oauth/access_token",
        "user_url": "https://api.github.com/user",
        "emails_url": "https://api.github.com/user/emails",
    },
    "google": {
        "client_id": env("GOOGLE_CLIENT_ID", default=""),
        "client_secret": env("GOOGLE_CLIENT_SECRET", default=""),
        "token_url": "https://oauth2.googleapis.com/token",
        "user_url": "https://openidconnect.googleapis.com/v1/userinfo",
    },
}

# --------------------------------------------------------------------------
# FR-ORG-002 — recognized institutional domains for the domain-matched
# fast-track into FR-ORG-003's pending review queue (NOT auto-verification
# -- a Platform Admin always makes the final verified/not-verified call;
# see apps/organizations/services.py::_attempt_domain_fast_track).
# Comma-separated in RECOGNIZED_INSTITUTIONAL_DOMAINS env var, e.g.:
#   RECOGNIZED_INSTITUTIONAL_DOMAINS=aau.edu.et,aastu.edu.et,bdu.edu.et
# The two defaults below are only a working example (both confirmed live
# domains) -- this is a business/partnerships decision, not an engineering
# one, and the real list should be compiled and signed off by whoever owns
# the university/government relationships (Doc 10 Sec 5), then set via env
# rather than expanded here.
# --------------------------------------------------------------------------

RECOGNIZED_INSTITUTIONAL_DOMAINS = env.list(
    "RECOGNIZED_INSTITUTIONAL_DOMAINS",
    default=["aau.edu.et", "aastu.edu.et"],
)