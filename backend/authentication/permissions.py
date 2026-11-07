from rest_framework.permissions import BasePermission
import os

class IsAdminOrSuperuser(BasePermission):
    """
    Gold-Standard Admin Permission Guard:
    Strictly permits access ONLY to authenticated users with is_staff or is_superuser flags.
    Blocks all anonymous visitors, regular learners, and unauthorized bots.
    """
    message = "Admin access restricted. Valid staff or superuser credentials required."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and
            user.is_authenticated and
            user.is_active and
            (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
        )


class IsActiveUser(BasePermission):
    """
    Permits access only to authenticated, non-banned active users.
    """
    message = "Authentication required. Active user account necessary."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_active)


class HasInternalAIKey(BasePermission):
    """
    Protects inter-service calls between FastAPI and Django.
    """
    message = "Unauthorized internal service call."

    def has_permission(self, request, view):
        internal_key = request.headers.get("X-Internal-Key")
        expected_key = os.environ.get("AI_INTERNAL_KEY")
        return bool(expected_key and internal_key == expected_key)
