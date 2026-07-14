"""
core.managers -- TenantScopedManager

Per Design Spec Sec 3.3: row-level multi-tenancy. Every tenant-scoped model
elsewhere in the project must use this base manager and declare its scoping
field. Raises at import/query time (not silently) if a subclass omits its
scoping field -- turning cross-tenant data leaks (BR-009) into a
startup-time error rather than a runtime bug.
"""

from django.db import models


class TenantScopedManager(models.Manager):
    #: Subclasses must set this to the FK field name used to scope rows,
    #: e.g. "organization" or "hackathon".
    scope_field: str | None = None

    def get_queryset(self):
        if not self.scope_field:
            raise NotImplementedError(
                "TenantScopedManager subclasses must declare `scope_field` "
                "(see Design Spec Sec 3.3 / BR-009)."
            )
        return super().get_queryset()
