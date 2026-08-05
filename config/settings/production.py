"""
Production settings.
Per Doc 08 Sec 3.2: secrets are injected at runtime via environment
variables from a managed secrets manager — never committed, never baked
into the image layer.
"""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# base.py's CACHES default (LocMemCache) is per-process -- fine for local
# dev, wrong here. DRF's ScopedRateThrottle (login/signup/oauth_login/
# password_reset_request throttles, config/settings/base.py) stores its
# request counters in the Django cache; with N gunicorn/uvicorn workers
# each holding its own LocMemCache, "30/min" would actually mean
# "30/min per worker" -- N times more permissive than intended, and
# worse, inconsistent depending on which worker handles which request.
# A shared backend closes that gap. Reuses REDIS_URL (already required
# for Celery) on a separate logical DB so cache keys and the Celery
# broker's own keys never collide.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": env("CACHE_URL", default=REDIS_URL.rsplit("/", 1)[0] + "/1"),
    }
}
