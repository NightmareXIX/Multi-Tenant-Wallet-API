from rest_framework.permissions import BasePermission

from .models import Tenant


class HasTenant(BasePermission):
    """Allows the request only when ApiKeyAuthentication resolved a tenant."""

    def has_permission(self, request, view):
        return isinstance(request.auth, Tenant)
