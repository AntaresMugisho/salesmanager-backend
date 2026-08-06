from django.db.models import (
    Case,
    ExpressionWrapper,
    F,
    IntegerField,
    Sum,
    When,
)
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, viewsets
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Site
from apps.catalogue.querysets import article_queryset
from apps.catalogue.serializers import ArticleSerializer
from apps.common.dates import today_start
from apps.common.filters import CamelCaseQueryParamsMixin
from apps.common.pagination import StandardPagination
from apps.common.permissions import IsManagerOrAbove
from apps.stock.filters import MovementFilterSet, TransactionFilterSet
from apps.stock.models import StockLevel, StockMovement, StockTransaction
from apps.stock.serializers import (
    MovementCreateSerializer,
    StockMovementSerializer,
    StockTransactionDetailSerializer,
    StockTransactionSerializer,
    TransactionCreateSerializer,
)
from apps.stock.predicates import low_stock_queryset
from apps.stock.services import apply_movement, create_transaction


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


class LowStockView(CamelCaseQueryParamsMixin, ListAPIView):
    serializer_class = ArticleSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ["name", "sku"]

    def get_queryset(self):
        return low_stock_queryset(article_queryset(site=self.site)).order_by(
            # Ruptures first, then ascending quantity. Not a cover ratio —
            # there is no consumption-rate data to compute one from.
            Case(
                When(stock_quantity__lte=0, then=0),
                default=1,
                output_field=IntegerField(),
            ),
            "stock_quantity",
            "name",
        )

    @property
    def site(self):
        if not hasattr(self, "_site"):
            self._site = Site.objects.current()
        return self._site

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["site"] = self.site
        return context


class DashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        site = Site.objects.current()
        articles = article_queryset(site=site)

        # Summed in SQL rather than in Python: the frontend loops over every
        # level to compute this, which is fine against IndexedDB and is not
        # fine against a shop with a few thousand articles.
        #
        # output_field goes inside ExpressionWrapper, never as an annotate()
        # kwarg — as a kwarg it would silently create an annotation *named*
        # `output_field`.
        stock_value = (
            StockLevel.objects.filter(site=site)
            .annotate(
                value=ExpressionWrapper(
                    F("quantity") * F("article__purchase_price"),
                    output_field=IntegerField(),
                )
            )
            .aggregate(total=Sum("value"))["total"]
            or 0
        )

        return Response(
            {
                "article_count": articles.filter(is_active=True).count(),
                "stock_value": stock_value,
                "low_stock_count": low_stock_queryset(articles).count(),
                "movements_today": StockMovement.objects.filter(
                    site=site, created_at__gte=today_start()
                ).count(),
            }
        )


class TransactionViewSet(
    CamelCaseQueryParamsMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Create, list and retrieve only.

    A transaction is immutable — correcting one means posting a new,
    compensating transaction. The absent update and destroy mixins are what
    make PATCH and DELETE return 405; no explicit handling is needed.
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = TransactionFilterSet
    search_fields = ["reference", "user_reference", "supplier_name", "note"]

    def get_queryset(self):
        return StockTransaction.objects.select_related("site", "supplier", "user")

    def get_serializer_class(self):
        if self.action == "create":
            return TransactionCreateSerializer
        if self.action == "retrieve":
            return StockTransactionDetailSerializer
        return StockTransactionSerializer

    def get_permissions(self):
        classes = [IsManagerOrAbove] if self.action == "create" else [IsAuthenticated]
        return [permission() for permission in classes]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        header = create_transaction(
            type=data["type"],
            reason=data["reason"],
            lines=data["lines"],
            user=request.user,
            site=Site.objects.current(),
            supplier=data.get("supplier"),
            user_reference=data.get("reference"),
            note=data.get("note"),
        )

        return Response(StockTransactionSerializer(header).data, status=201)
