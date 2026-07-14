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
