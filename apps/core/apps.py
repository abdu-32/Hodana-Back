from pathlib import Path
import socket
from django.apps import AppConfig

_orig_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    if family == socket.AF_UNSPEC:
        family = socket.AF_INET
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _getaddrinfo_ipv4_only


def safe_watch_for_translation_changes(sender, **kwargs):
    """
    Register file watchers for .mo files only for directories that actually exist.
    Prevents unhandled OSError [Errno 5] EIO when StatReloader polls non-existent
    paths across Windows Docker bind mounts during development.
    """
    from django.conf import settings
    from django.apps import apps
    from django.utils.translation import reloader as trans_reloader

    if settings.USE_I18N:
        directories = []
        root_locale = Path("locale")
        if root_locale.is_dir():
            directories.append(root_locale)

        for config in apps.get_app_configs():
            if not trans_reloader.is_django_module(config.module):
                app_locale = Path(config.path) / "locale"
                if app_locale.is_dir():
                    directories.append(app_locale)

        for p in settings.LOCALE_PATHS:
            p_path = Path(p)
            if p_path.is_dir():
                directories.append(p_path)

        for path in directories:
            sender.watch_dir(path, "**/*.mo")


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self):
        from django.utils import autoreload
        from django.utils.translation import reloader as trans_reloader

        autoreload.autoreload_started.disconnect(
            trans_reloader.watch_for_translation_changes,
            dispatch_uid="translation_file_changed",
        )
        autoreload.autoreload_started.connect(
            safe_watch_for_translation_changes,
            dispatch_uid="safe_translation_file_changed",
        )

