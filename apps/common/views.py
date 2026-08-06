"""The shared catalogue viewset.

Every list endpoint in sub-projects 2–6 subclasses this. It exists so the
permission map, the camelCase query translation and the pagination class are
declared once: a rule copied into a dozen viewsets is a rule that will
eventually be wrong in one of them, and the failure — a cashier able to delete
an article — is silent until someone tries it.
"""

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets

from apps.common.filters import AliasedOrderingFilter, CamelCaseQueryParamsMixin
from apps.common.pagination import StandardPagination
from apps.common.permissions import (
    IsManagerOrAbove,
    IsOwner,
    RoleScopedPermissionMixin,
)


class CatalogueViewSet(
    RoleScopedPermissionMixin, CamelCaseQueryParamsMixin, viewsets.ModelViewSet
):
    """Read for anyone authenticated, write for manager and above, delete for
    the owner.

    Subclasses set `queryset` and `serializer_class`, and may set
    `search_fields`, `ordering_fields`, `ordering_aliases` and
    `filterset_class`. A subclass needing a different map overrides
    `permission_map` rather than `get_permissions`.
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, AliasedOrderingFilter]

    # `create`, `update` and `partial_update` are the only ModelViewSet actions
    # reached by POST/PUT/PATCH, so this is exactly the method-based rule it
    # replaces — stated as actions, which is what DRF dispatches on.
    permission_map = {
        "create": IsManagerOrAbove,
        "update": IsManagerOrAbove,
        "partial_update": IsManagerOrAbove,
        "destroy": IsOwner,
    }
