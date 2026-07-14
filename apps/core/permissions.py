"""
core.permissions -- shared DRF permission classes

Per Design Spec Sec 4.3:
- IsPlatformAdmin: checks the global admin boolean flag on the account.
- HasScopedRole: checks apps.accounts.RoleAssignment for
  (user, role, scope_type, scope_id) rather than trusting any JWT claim.
"""

from rest_framework.permissions import BasePermission


class IsPlatformAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "is_platform_admin", False)
        )


class HasScopedRole(BasePermission):
    """Usage: configure with a role + scope_type per view; resolves against
    apps.accounts.RoleAssignment, never a token claim (Design Spec Sec 4.3)."""

    def has_permission(self, request, view):
        raise NotImplementedError
