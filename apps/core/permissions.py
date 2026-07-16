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
    apps.accounts.RoleAssignment, never a token claim (Design Spec Sec 4.3).

    View config:
        required_roles = ["organizer"]       # one or more RoleAssignment.role values
        scope_type = "hackathon"             # matches RoleAssignment.scope_type
        scope_url_kwarg = "hackathon_id"     # URL kwarg holding the scope_id (defaults to "pk")
    """

    def has_permission(self, request, view):
        from apps.accounts.models import RoleAssignment

        if not (request.user and request.user.is_authenticated):
            return False

        required_roles = getattr(view, "required_roles", None)
        scope_type = getattr(view, "scope_type", None)
        if not required_roles or not scope_type:
            raise NotImplementedError(
                "HasScopedRole requires `required_roles` and `scope_type` "
                "to be set on the view."
            )

        scope_url_kwarg = getattr(view, "scope_url_kwarg", "pk")
        scope_id = view.kwargs.get(scope_url_kwarg)
        if not scope_id:
            return False

        return RoleAssignment.objects.filter(
            user=request.user,
            role__in=required_roles,
            scope_type=scope_type,
            scope_id=scope_id,
        ).exists()