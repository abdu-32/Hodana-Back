"""
core.managers -- TenantScopedManager

Per Design Spec Sec 3.3: row-level multi-tenancy. Every tenant-scoped model
elsewhere in the project must use this base manager and declare its scoping
field.

Two guarantees, not one:
1. Raises at query time if a subclass omits `scope_field` -- turns a
   forgotten declaration into a startup-time error (BR-009).
2. `scoped_to(tenant_id)` is the ONLY sanctioned way for a services.py
   function to list more than one row of a tenant-scoped model. Any
   "list X within a tenant" query must call `Model.objects.scoped_to(id)`,
   never `.objects.filter(...)` or `.objects.all()` directly -- those bypass
   this entirely and are a cross-tenant leak waiting to happen. Fetching a
   single row by its own primary key (the `_get_x_or_404` pattern already
   used throughout services.py) is unaffected -- that's an ownership check,
   not a listing, and stays exactly as it is.
"""

from django.db import models


class TenantScopedManager(models.Manager):
    scope_field: str | None = None

    def get_queryset(self):
        if not self.scope_field:
            raise NotImplementedError(
                "TenantScopedManager subclasses must declare `scope_field` "
                "(see Design Spec Sec 3.3 / BR-009)."
            )
        return super().get_queryset()

    def scoped_to(self, tenant_id):
        """Required entry point for any multi-row query against a
        tenant-scoped model. e.g. Team.objects.scoped_to(hackathon.id)
        for 'all teams in this hackathon', never Team.objects.filter(...)."""
        return self.get_queryset().filter(**{f"{self.scope_field}_id": tenant_id})