"""
Development settings — local Docker Compose, seeded fixture data.
Per Design Spec Sec 8.2 / Doc 08 Sec 3.1.
"""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

# Local dev default is SQLite unless DATABASE_URL is set (docker-compose sets it).
# See docker-compose.yml — the `db` service provides Postgres.

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")

# Relax throttle rates in local development mode for seamless testing
REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
    "email_verification_resend": "100/min",
    "login": "1000/min",
    "signup": "1000/hour",
    "oauth_login": "1000/min",
    "password_reset_request": "1000/hour",
}