from django.db.models import (
    Case,
    ExpressionWrapper,
    F,
    IntegerField,
    Sum,
    When,
)
from django.utils.translation import gettext_lazy as _
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, serializers, viewsets
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
from apps.common.permissions import IsManagerOrAbove, RoleScopedPermissionMixin
from apps.common.references import (
    resolve_offline_write,
    validate_device_reference,
)
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
    RoleScopedPermissionMixin,
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

    permission_map = {"create": IsManagerOrAbove}

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        device = resolve_offline_write(request)

        # Before apply_movement, so a replay returns the movement it already
        # posted rather than moving the level a second time.
        movement_id = data.get("id")
        if movement_id:
            existing = StockMovement.objects.filter(pk=movement_id).first()
            if existing:
                return Response(StockMovementSerializer(existing).data, status=200)

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
            movement_id=movement_id,
            allow_negative=bool(device),
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
    RoleScopedPermissionMixin,
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

    permission_map = {"create": IsManagerOrAbove}

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        device = resolve_offline_write(request)
        document_reference = data.get("document_reference")
        transaction_id = data.get("id")

        if document_reference and not device:
            raise serializers.ValidationError(
                {
                    "documentReference": [
                        _("Un numéro de document exige l'en-tête X-Device-Code.")
                    ]
                }
            )

        # Before the reference checks, for the reason given in SaleViewSet: a
        # replay carries the same reference as the transaction it replays.
        if transaction_id:
            existing = StockTransaction.objects.filter(pk=transaction_id).first()
            if existing:
                return Response(StockTransactionSerializer(existing).data, status=200)

        if document_reference:
            validate_device_reference(
                document_reference,
                prefix="TR",
                device_code=device.code,
                field="documentReference",
            )
            # Explicit for the same reason as on sales: this serializer is a
            # plain Serializer, so an unchecked duplicate would reach the
            # column constraint and render as a 500.
            if StockTransaction.objects.filter(reference=document_reference).exists():
                raise serializers.ValidationError(
                    {
                        "documentReference": [
                            _("Ce numéro de document a déjà été enregistré.")
                        ]
                    }
                )

        header = create_transaction(
            type=data["type"],
            reason=data["reason"],
            lines=data["lines"],
            user=request.user,
            site=Site.objects.current(),
            supplier=data.get("supplier"),
            # Unchanged: the supplier's delivery-note number, not the
            # document's own reference.
            user_reference=data.get("reference"),
            note=data.get("note"),
            reference=document_reference,
            transaction_id=transaction_id,
            allow_negative=bool(device),
        )

        return Response(StockTransactionSerializer(header).data, status=201)
