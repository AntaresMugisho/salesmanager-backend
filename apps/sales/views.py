from django.utils.translation import gettext_lazy as _
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import Site
from apps.common.exceptions import Conflict
from apps.common.filters import CamelCaseQueryParamsMixin
from apps.common.pagination import StandardPagination
from apps.common.permissions import IsManagerOrAbove, RoleScopedPermissionMixin
from apps.common.views import CatalogueViewSet
from apps.sales.filters import SaleFilterSet
from apps.sales.models import Customer
from apps.sales.querysets import sale_queryset
from apps.sales.serializers import (
    CustomerSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
    SaleCancelSerializer,
    SaleCreateSerializer,
    SaleDetailSerializer,
    SaleSerializer,
)
from apps.sales.services import add_payment, cancel_sale, create_sale


class CustomerViewSet(CatalogueViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer
    search_fields = ["name", "contact_name", "email", "phone"]
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]

    def perform_destroy(self, instance):
        used = instance.sales.count()
        if used:
            raise Conflict(
                _(
                    "Ce client est lié à %(count)d vente%(plural)s et ne peut "
                    "pas être supprimé. Archivez-le à la place."
                )
                % {"count": used, "plural": "s" if used > 1 else ""}
            )
        instance.delete()


class SaleViewSet(
    RoleScopedPermissionMixin,
    CamelCaseQueryParamsMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Create, list and retrieve. A sale's only mutation is cancellation,
    which is its own action — there is no update and no destroy."""

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = SaleFilterSet
    search_fields = ["reference", "customer_name", "note"]

    # Cashiers work the till: they create sales and take payments, both of
    # which fall to `default_permission` (IsAuthenticated). They do not
    # cancel — that is the manager's call. This map is inverted from the
    # catalogue's, where cashiers write nothing.
    permission_map = {"cancel": IsManagerOrAbove}

    def get_queryset(self):
        queryset = sale_queryset()
        if self.action == "retrieve":
            return queryset.prefetch_related("lines", "payments")
        return queryset

    def get_serializer_class(self):
        if self.action == "create":
            return SaleCreateSerializer
        if self.action == "retrieve":
            return SaleDetailSerializer
        return SaleSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        sale = create_sale(
            lines=data["lines"],
            user=request.user,
            site=Site.objects.current(),
            customer=data.get("customer"),
            discount=data.get("discount", 0),
            discount_rate=data.get("discount_rate"),
            note=data.get("note"),
        )

        # Re-read through the annotated queryset: a bare Sale has no
        # paid_amount or line_count, and the response serializer needs both.
        annotated = sale_queryset().get(pk=sale.pk)
        return Response(
            SaleSerializer(annotated, context=self.get_serializer_context()).data,
            status=201,
        )

    @action(detail=True, methods=["post"], url_path="payments")
    def payments(self, request, pk=None):
        sale = self.get_object()
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payment = add_payment(
            sale=sale,
            amount=data["amount"],
            method=data["method"],
            paid_at=data["paid_at"],
            user=request.user,
            reference=data.get("reference"),
            note=data.get("note"),
        )

        return Response(PaymentSerializer(payment).data, status=201)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        sale = self.get_object()
        serializer = SaleCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        cancel_sale(
            sale=sale, reason=serializer.validated_data.get("reason"), user=request.user
        )

        annotated = sale_queryset().get(pk=sale.pk)
        return Response(
            SaleSerializer(annotated, context=self.get_serializer_context()).data
        )
