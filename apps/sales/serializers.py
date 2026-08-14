import re

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.catalogue.models import Article
from apps.common.collation import collation_key
from apps.sales.models import Customer, Payment, Sale, SaleLine
from apps.sales.totals import compute_balance

PHONE_PATTERN = re.compile(r"^[\d\s+().-]{6,20}$")


def french_sort_key(value: str) -> tuple[str, str]:
    """Sort invoice lines by article name, the way a French reader expects.

    Delegates to `apps.common.collation.collation_key`. This used to carry its
    own NFKD implementation, which had no ligature table and therefore sorted
    « Œufs » after « Zeste » on a printed invoice — Unicode gives Œ no
    compatibility decomposition, so NFKD alone does not touch it.

    The original value is kept as a secondary key so names that differ only by
    accent or case still order deterministically rather than by chance.
    """
    return (collation_key(value), value)


class CustomerSerializer(serializers.ModelSerializer):
    """The frontend's `Customer`. Validation mirrors
    `features/customers/schema.ts`."""

    contact_name = serializers.CharField(
        max_length=80, required=False, allow_blank=True, allow_null=True
    )
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    address = serializers.CharField(
        max_length=200, required=False, allow_blank=True, allow_null=True
    )
    tax_number = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    notes = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )

    OPTIONAL_FIELDS = (
        "contact_name",
        "email",
        "phone",
        "address",
        "tax_number",
        "notes",
    )

    class Meta:
        model = Customer
        fields = [
            "id",
            "name",
            "contact_name",
            "email",
            "phone",
            "address",
            "tax_number",
            "notes",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_name(self, value):
        name = value.strip()
        if len(name) < 2:
            raise serializers.ValidationError(
                _("Le nom doit contenir au moins 2 caractères.")
            )
        if len(name) > 80:
            raise serializers.ValidationError(
                _("Le nom ne peut pas dépasser 80 caractères.")
            )
        existing = Customer.objects.filter(name__iexact=name)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError(_("Un client porte déjà ce nom."))
        return name

    def validate_phone(self, value):
        if not value or not value.strip():
            return value
        if not PHONE_PATTERN.match(value.strip()):
            raise serializers.ValidationError(_("Numéro de téléphone invalide."))
        return value

    def validate(self, attrs):
        for field in self.OPTIONAL_FIELDS:
            if field in attrs:
                value = attrs[field]
                attrs[field] = value.strip() or None if value else None
        return attrs


class CustomerRefSerializer(serializers.ModelSerializer):
    """The frontend's `CustomerRef`, built from the sale's own snapshot."""

    id = serializers.UUIDField(source="customer_id", read_only=True)
    name = serializers.CharField(source="customer_name", read_only=True)

    class Meta:
        model = Sale
        fields = ["id", "name"]


class SaleCustomerDetailSerializer(CustomerRefSerializer):
    """The frontend's `SaleCustomerDetail` — the billing block on an invoice."""

    address = serializers.CharField(source="customer_address", read_only=True)
    tax_number = serializers.CharField(source="customer_tax_number", read_only=True)

    class Meta(CustomerRefSerializer.Meta):
        fields = CustomerRefSerializer.Meta.fields + ["address", "tax_number"]


class SaleLineSerializer(serializers.ModelSerializer):
    """The frontend's `SaleLine`. Every field is the snapshot."""

    class Meta:
        model = SaleLine
        fields = [
            "id",
            "article_id",
            "article_name",
            "article_sku",
            "unit",
            "quantity",
            "unit_price",
            "unit_cost",
            "vat_rate",
            "line_total",
            "discount_share",
            "vat_amount",
        ]


class PaymentSerializer(serializers.ModelSerializer):
    """The frontend's `Payment`."""

    sale_id = serializers.UUIDField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "sale_id",
            "amount",
            "method",
            "paid_at",
            "reference",
            "note",
            "user_id",
            "user_name",
            "created_at",
        ]


class SaleSerializer(serializers.ModelSerializer):
    """The frontend's `Sale`.

    `paidAmount` comes from the queryset annotation; `balance` and
    `paymentStatus` are derived from it here. None of the three is a column.
    """

    site_id = serializers.UUIDField(read_only=True)
    customer_id = serializers.UUIDField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)
    customer = serializers.SerializerMethodField()
    line_count = serializers.IntegerField(read_only=True)
    paid_amount = serializers.IntegerField(read_only=True)
    balance = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()

    class Meta:
        model = Sale
        fields = [
            "id",
            "reference",
            "site_id",
            "customer_id",
            "customer",
            "status",
            "subtotal",
            "discount",
            "discount_rate",
            "total",
            "vat_total",
            "note",
            "cancelled_at",
            "cancel_reason",
            "line_count",
            "paid_amount",
            "balance",
            "payment_status",
            "user_id",
            "user_name",
            "created_at",
        ]

    def get_customer(self, obj):
        if obj.customer_id is None:
            return None
        return CustomerRefSerializer(obj).data

    def get_balance(self, obj) -> int:
        # The rule lives in `apps.sales.totals` so the sale detail and the
        # sales report cannot drift apart.
        return compute_balance(obj.total, obj.paid_amount, obj.status)

    def get_payment_status(self, obj) -> str:
        if obj.paid_amount <= 0:
            return "UNPAID"
        if obj.paid_amount >= obj.total:
            return "PAID"
        return "PARTIAL"


class SaleDetailSerializer(SaleSerializer):
    """The frontend's `SaleDetail` — the list shape plus lines and payments,
    with the customer widened to the invoice billing block."""

    customer = serializers.SerializerMethodField()
    lines = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()

    class Meta(SaleSerializer.Meta):
        fields = SaleSerializer.Meta.fields + ["lines", "payments"]

    def get_customer(self, obj):
        if obj.customer_id is None:
            return None
        return SaleCustomerDetailSerializer(obj).data

    def get_lines(self, obj):
        rows = sorted(obj.lines.all(), key=lambda row: french_sort_key(row.article_name))
        return SaleLineSerializer(rows, many=True).data

    def get_payments(self, obj):
        # Model ordering is already (paid_at, id); this reads from the
        # prefetched cache rather than issuing a second query.
        return PaymentSerializer(obj.payments.all(), many=True).data


class SaleLineInputSerializer(serializers.Serializer):
    """One row of `SaleCreateDto.lines`."""

    article_id = serializers.PrimaryKeyRelatedField(
        source="article",
        queryset=Article.objects.all(),
        error_messages={"does_not_exist": _("Cet article n'existe plus.")},
    )
    quantity = serializers.IntegerField(
        min_value=1,
        error_messages={
            "min_value": _("La quantité doit être supérieure à zéro."),
            "invalid": _("La quantité doit être supérieure à zéro."),
        },
    )
    unit_price = serializers.IntegerField(
        min_value=0,
        error_messages={
            "min_value": _("Le prix unitaire est invalide."),
            "invalid": _("Le prix unitaire est invalide."),
        },
    )


class SaleCreateSerializer(serializers.Serializer):
    """The frontend's `SaleCreateDto`.

    `discount` arrives already resolved to cents — the form turns a percentage
    into an amount before sending, and `discountRate` records which it was.

    `lines` keeps DRF's default `allow_empty=True` and rejects an empty list in
    `validate_lines`: `allow_empty=False` produces
    `{"lines": {"non_field_errors": [...]}}`, which reaches the client as
    `lines.nonFieldErrors` — a key no form field is mounted on, so the user
    would see nothing at all.
    """

    customer_id = serializers.PrimaryKeyRelatedField(
        source="customer",
        queryset=Customer.objects.all(),
        required=False,
        allow_null=True,
        default=None,
        error_messages={"does_not_exist": _("Ce client n'existe plus.")},
    )
    discount = serializers.IntegerField(
        min_value=0,
        required=False,
        default=0,
        error_messages={
            "min_value": _("La remise ne peut pas être négative."),
            "invalid": _("La remise ne peut pas être négative."),
        },
    )
    discount_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=0,
        max_value=100,
        required=False,
        allow_null=True,
        default=None,
    )
    note = serializers.CharField(
        max_length=300, required=False, allow_blank=True, allow_null=True, default=None
    )
    # Present only on a replayed offline sale; the view refuses it without an
    # X-Device-Code header and validates it against that device's series.
    # Named `document_reference` rather than `reference` to stay identical to
    # `TransactionCreateSerializer`, where plain `reference` is already taken
    # by the supplier's delivery-note number.
    document_reference = serializers.CharField(
        max_length=20, required=False, allow_null=True, default=None
    )
    # Minted on the device so a queued sale keeps one URL either side of sync.
    # Optional: an online sale lets the model default fire.
    id = serializers.UUIDField(required=False, allow_null=True, default=None)
    lines = SaleLineInputSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError(
                _("Ajoutez au moins un article à la vente.")
            )
        return value

    def validate(self, attrs):
        seen = set()
        for index, row in enumerate(attrs["lines"]):
            article = row["article"]
            if article.id in seen:
                raise serializers.ValidationError(
                    {
                        f"lines.{index}.article_id": [
                            _("Cet article est déjà présent dans la vente.")
                        ]
                    }
                )
            seen.add(article.id)
        return attrs


class PaymentCreateSerializer(serializers.Serializer):
    """The frontend's `PaymentCreateDto`."""

    # Minted on the device when the payment is queued offline, so replaying it
    # is a no-op rather than a second payment. Absent on the online path.
    id = serializers.UUIDField(required=False, allow_null=True, default=None)
    amount = serializers.IntegerField(
        min_value=1,
        error_messages={
            "min_value": _("Le montant doit être supérieur à zéro."),
            "invalid": _("Le montant doit être supérieur à zéro."),
        },
    )
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    #: A bare calendar date from a picker; the service widens it to local noon.
    paid_at = serializers.DateField()
    reference = serializers.CharField(
        max_length=40, required=False, allow_blank=True, allow_null=True, default=None
    )
    note = serializers.CharField(
        max_length=300, required=False, allow_blank=True, allow_null=True, default=None
    )


class SaleCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(
        max_length=300, required=False, allow_blank=True, allow_null=True, default=None
    )
