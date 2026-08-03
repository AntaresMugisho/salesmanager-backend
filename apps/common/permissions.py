"""Role permissions.

DRF renders `message` as the 403's detail, and the error envelope keeps a
bare-string detail as the envelope's `message` — so these strings reach the
user's toast directly and must be French.

The full role matrix lives in the spec. Only the owner-gated rows are
enforceable in sub-project 1; the rest is implemented as its sub-project
lands.
"""

from django.utils.translation import gettext_lazy as _
from rest_framework.permissions import SAFE_METHODS, BasePermission


def _active(request) -> bool:
    user = getattr(request, "user", None)
    return bool(user and user.is_authenticated and user.is_active)


class IsOwner(BasePermission):
    message = _("Cette action est réservée au propriétaire.")

    def has_permission(self, request, view) -> bool:
        return _active(request) and request.user.is_owner


class IsManagerOrAbove(BasePermission):
    message = _("Cette action est réservée au gérant ou au propriétaire.")

    def has_permission(self, request, view) -> bool:
        return _active(request) and request.user.is_manager_or_above


class ReadOnlyForCashier(BasePermission):
    """Everyone authenticated may read; only manager and above may write."""

    message = _("Cette action est réservée au gérant ou au propriétaire.")

    def has_permission(self, request, view) -> bool:
        if not _active(request):
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.is_manager_or_above
