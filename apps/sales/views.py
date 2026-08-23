from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.translation import gettext_lazy as _
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import Site
from apps.common.exceptions import Conflict
from apps.common.filters import CamelCaseQueryParamsMixin, StrictBooleanField
from apps.common.pagination import StandardPagination
from apps.common.references import (
    resolve_offline_write,
    validate_device_reference,
)
from apps.common.permissions import IsManagerOrAbove, RoleScopedPermissionMixin
from apps.common.views import CatalogueViewSet
from apps.sales.filters import SaleFilterSet
from apps.sales.models import Customer, Payment, Sale
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

    def _wants_lines(self) -> bool:
        """`withLines`, arriving as `with_lines`.

        CamelCaseQueryParamsMixin rewrites the query string in `initial()`,
        before any handler runs, so the snake_case name is the one to read.
        StrictBooleanField rather than a truthiness test: `withLines=banana`
        must be refused, not silently mean false — a mirror quietly filled
        with lineless sales has no symptom until an outage.
        """
        raw = self.request.query_params.get("with_lines")
        if raw is None:
            return False
        try:
            return bool(StrictBooleanField().clean(raw))
        except DjangoValidationError as exc:
            # DRF's handler does not translate Django's ValidationError to a
            # 400 on its own; unwrapped it surfaces as a 500.
            raise serializers.ValidationError({"withLines": exc.messages}) from exc

    def get_queryset(self):
        queryset = sale_queryset()
        if self.action == "retrieve" or (
            self.action == "list" and self._wants_lines()
        ):
            return queryset.prefetch_related("lines", "payments")
        return queryset

    def get_serializer_class(self):
        if self.action == "create":
            return SaleCreateSerializer
        if self.action == "retrieve":
            return SaleDetailSerializer
        if self.action == "list" and self._wants_lines():
            return SaleDetailSerializer
        return SaleSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        device = resolve_offline_write(request)
        reference = data.get("document_reference")
        sale_id = data.get("id")

        if reference and not device:
            raise serializers.ValidationError(
                {
                    "documentReference": [
                        _("Un numéro de document exige l'en-tête X-Device-Code.")
                    ]
                }
            )

        # Before any reference check, and deliberately: a replay carries the
        # same reference as the sale it is replaying, so a uniqueness check
        # placed first would reject exactly the requests this exists to
        # accept. The queue is retrying a sale the server already committed;
        # returning it — rather than 409 — is what lets a client drain its
        # queue after a sync that died half way.
        if sale_id:
            existing = sale_queryset().filter(pk=sale_id).first()
            if existing:
                return Response(
                    SaleSerializer(
                        existing, context=self.get_serializer_context()
                    ).data,
                    status=200,
                )

        if reference:
            validate_device_reference(
                reference,
                prefix="FA",
                device_code=device.code,
                field="documentReference",
            )
            # Explicit, because SaleCreateSerializer is a plain Serializer and
            # validates no uniqueness of its own. Without this the duplicate
            # reaches the column's unique constraint and DRF renders the
            # IntegrityError as a 500. Reaching here means a *different* sale
            # reusing a reference already taken — a replay would have returned
            # above — which is a client bug and should read as one.
            if Sale.objects.filter(reference=reference).exists():
                raise serializers.ValidationError(
                    {
                        "documentReference": [
                            _("Ce numéro de document a déjà été enregistré.")
                        ]
                    }
                )

        sale = create_sale(
            lines=data["lines"],
            user=request.user,
            site=Site.objects.current(),
            customer=data.get("customer"),
            discount=data.get("discount", 0),
            discount_rate=data.get("discount_rate"),
            note=data.get("note"),
            reference=reference,
            sale_id=sale_id,
            allow_negative=bool(device),
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

        # Before `add_payment`, so a replay returns the payment it already
        # made rather than tripping the overpayment guard on the way in.
        payment_id = data.get("id")
        if payment_id:
            existing = Payment.objects.filter(pk=payment_id).first()
            if existing:
                # Looked up by pk alone, then checked: filtering by sale as
                # well would let a colliding id reach the pk constraint as a
                # 500, and returning it unchecked would hand back a different
                # sale's payment.
                if existing.sale_id != sale.id:
                    raise serializers.ValidationError(
                        {
                            "id": [
                                _("Ce paiement est déjà rattaché à une autre vente.")
                            ]
                        }
                    )
                return Response(PaymentSerializer(existing).data, status=200)

        payment = add_payment(
            sale=sale,
            amount=data["amount"],
            method=data["method"],
            paid_at=data["paid_at"],
            user=request.user,
            reference=data.get("reference"),
            note=data.get("note"),
            payment_id=payment_id,
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
