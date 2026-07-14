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
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "drf_spectacular",
    # Re-enable when background jobs are actually needed (see README):
    # "django_celery_beat",
    # "django_celery_results",
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
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": (
        "rest_framework.permissions.IsAuthenticated",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.ScopedRateThrottle",
    ),
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
# Celery + Redis — DISABLED for now. Re-enable when you write the first
# task that actually needs "run this later" or "run this on a schedule"
# (e.g. FR-NOTIFY email dispatch, or the submission-deadline lock job).
# To re-enable: uncomment this block + the two apps above, uncomment
# celery/redis/django-celery-* in requirements/base.txt, uncomment
# `redis`, `worker`, `beat` in docker-compose.yml, and uncomment the
# celery_app import in config/__init__.py.
# --------------------------------------------------------------------------

# REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

# CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
# CELERY_RESULT_BACKEND = "django-db"
# CELERY_ACCEPT_CONTENT = ["json"]
# CELERY_TASK_SERIALIZER = "json"
# CELERY_RESULT_SERIALIZER = "json"
# CELERY_TIMEZONE = TIME_ZONE

# CELERY_TASK_ROUTES = {
#     "apps.notifications.*": {"queue": "notifications"},
#     "apps.submissions.tasks.*": {"queue": "media"},
#     "apps.analytics.tasks.*": {"queue": "analytics"},
#     "apps.hackathons.tasks.*": {"queue": "scheduled"},
# }

CACHES = {
    "default": {
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
