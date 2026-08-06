from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import Site
from apps.common.filters import CamelCaseQueryParamsMixin
from apps.common.pagination import StandardPagination
from apps.common.permissions import IsManagerOrAbove
from apps.stock.filters import MovementFilterSet
from apps.stock.models import StockMovement
from apps.stock.serializers import MovementCreateSerializer, StockMovementSerializer
from apps.stock.services import apply_movement


class MovementViewSet(
    CamelCaseQueryParamsMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """List and create only. Movements are append-only: nothing updates or
    deletes one, and a correction is a new compensating movement."""

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = MovementFilterSet
    search_fields = ["article__name", "article__sku", "reference"]

    def get_queryset(self):
        return StockMovement.objects.select_related("article", "site", "user")

    def get_serializer_class(self):
        if self.action == "create":
            return MovementCreateSerializer
        return StockMovementSerializer

    def get_permissions(self):
        classes = [IsManagerOrAbove] if self.action == "create" else [IsAuthenticated]
        return [permission() for permission in classes]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        movement = apply_movement(
            article=data["article"],
            site=Site.objects.current(),
            type=data["type"],
            reason=data["reason"],
            quantity=data["quantity"],
            unit_cost=data.get("unit_cost"),
            reference=data.get("reference"),
            note=data.get("note"),
            user=request.user,
        )

        return Response(StockMovementSerializer(movement).data, status=201)
