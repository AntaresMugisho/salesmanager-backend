from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.catalogue.models import Article, Supplier
from apps.catalogue.serializers import ArticleRefSerializer
from apps.stock.models import StockMovement, StockTransaction


class StockMovementSerializer(serializers.ModelSerializer):
    """The frontend's `StockMovement`."""

    article = ArticleRefSerializer(read_only=True)
    article_id = serializers.UUIDField(source="article.id", read_only=True)
    site_id = serializers.UUIDField(source="site.id", read_only=True)
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    # Reads the model's `transaction_id` attname directly; DRF renders a
    # None attribute as null without help.
    transaction_id = serializers.UUIDField(read_only=True)
    sale_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id",
            "article_id",
            "article",
            "site_id",
            "type",
            "reason",
            "quantity",
            "quantity_before",
            "quantity_after",
            "unit_cost",
            "reference",
            "note",
            "transaction_id",
            "sale_id",
            "user_id",
            "user_name",
            "created_at",
        ]


class MovementCreateSerializer(serializers.Serializer):
    """The frontend's `MovementCreateDto`.

    A plain Serializer, not a ModelSerializer: the write shape and the read
    shape genuinely differ — `quantity` means a target rather than a delta on
    an ADJUSTMENT, and `quantityBefore` / `quantityAfter` are derived by
    `apply_movement`, never supplied.
    """

    # Minted on the device when the movement is queued offline, so replaying
    # it is a no-op rather than a second movement. Absent on the online path.
    id = serializers.UUIDField(required=False, allow_null=True, default=None)
    article_id = serializers.PrimaryKeyRelatedField(
        source="article", queryset=Article.objects.all()
    )
    type = serializers.ChoiceField(choices=StockMovement.Type.choices)
    reason = serializers.ChoiceField(choices=StockMovement.Reason.choices)
    quantity = serializers.IntegerField(min_value=0)
    unit_cost = serializers.IntegerField(
        min_value=0, required=False, allow_null=True, default=None
    )
    reference = serializers.CharField(
        max_length=40, required=False, allow_blank=True, allow_null=True, default=None
    )
    note = serializers.CharField(
        max_length=300, required=False, allow_blank=True, allow_null=True, default=None
    )

    def validate(self, attrs):
        # Zero is meaningful only for an ADJUSTMENT: counting a shelf and
        # finding it empty is a real correction, whereas an IN or OUT of zero
        # is a no-op the ledger should not record.
        if attrs["type"] != StockMovement.Type.ADJUSTMENT and attrs["quantity"] == 0:
            raise serializers.ValidationError(
                {"quantity": [_("La quantité doit être supérieure à zéro.")]}
            )
        return attrs


class StockTransactionSerializer(serializers.ModelSerializer):
    """The frontend's `StockTransaction`."""

    site_id = serializers.UUIDField(read_only=True)
    supplier_id = serializers.UUIDField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = StockTransaction
        fields = [
            "id",
            "reference",
            "site_id",
            "user_reference",
            "type",
            "reason",
            "supplier_id",
            "supplier_name",
            "note",
            "line_count",
            "total_quantity",
            "user_id",
            "user_name",
            "created_at",
        ]


class TransactionLineInputSerializer(serializers.Serializer):
    """One row of `TransactionCreateDto.lines`."""

    # Both messages are overridden so the user reads the frontend's wording
    # rather than DRF's generic French.
    article_id = serializers.PrimaryKeyRelatedField(
        source="article",
        queryset=Article.objects.all(),
        error_messages={"does_not_exist": _("Cet article n'existe plus.")},
    )
    quantity = serializers.IntegerField(
        min_value=0,
        error_messages={
            "min_value": _("La quantité doit être un nombre entier positif."),
            "invalid": _("La quantité doit être un nombre entier positif."),
        },
    )
    unit_cost = serializers.IntegerField(
        min_value=0, required=False, allow_null=True, default=None
    )


class TransactionCreateSerializer(serializers.Serializer):
    """The frontend's `TransactionCreateDto`.

    `lines` deliberately keeps DRF's default `allow_empty=True` and rejects an
    empty list in `validate_lines` instead. `allow_empty=False` produces
    `{"lines": {"non_field_errors": [...]}}`, which reaches the client as
    `lines.nonFieldErrors` — a key no form field is mounted on, so the user
    would see nothing at all.
    """

    type = serializers.ChoiceField(choices=StockMovement.Type.choices)
    reason = serializers.ChoiceField(choices=StockMovement.Reason.choices)
    supplier_id = serializers.PrimaryKeyRelatedField(
        source="supplier",
        queryset=Supplier.objects.all(),
        required=False,
        allow_null=True,
        default=None,
    )
    reference = serializers.CharField(
        max_length=40, required=False, allow_blank=True, allow_null=True, default=None
    )
    note = serializers.CharField(
        max_length=300, required=False, allow_blank=True, allow_null=True, default=None
    )
    # The document's own number, present only on a replayed offline
    # transaction. The `reference` field above is a different thing entirely:
    # the supplier's delivery-note number, which the user types in.
    document_reference = serializers.CharField(
        max_length=20, required=False, allow_null=True, default=None
    )
    # Minted on the device so a queued transaction keeps one identity either
    # side of sync. Optional: an online write lets the model default fire.
    id = serializers.UUIDField(required=False, allow_null=True, default=None)
    lines = TransactionLineInputSerializer(many=True)

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError(
                _("Ajoutez au moins un article à la transaction.")
            )
        return value

    def validate(self, attrs):
        seen = set()
        for index, line in enumerate(attrs["lines"]):
            article = line["article"]
            if article.id in seen:
                raise serializers.ValidationError(
                    {
                        f"lines.{index}.article_id": [
                            _("Cet article est déjà présent dans la transaction.")
                        ]
                    }
                )
            seen.add(article.id)

            # Zero is meaningful only for an ADJUSTMENT: counting a shelf and
            # finding it empty is a real correction, whereas an IN or OUT of
            # zero is a no-op the ledger should not record.
            if (
                attrs["type"] != StockMovement.Type.ADJUSTMENT
                and line["quantity"] == 0
            ):
                raise serializers.ValidationError(
                    {
                        f"lines.{index}.quantity": [
                            _("La quantité doit être supérieure à zéro.")
                        ]
                    }
                )
        return attrs


class StockTransactionLineSerializer(serializers.ModelSerializer):
    """The frontend's `StockTransactionLine`, resolved back from its movement.

    `movementId` rather than `id`: a line has no identity of its own, and the
    frontend uses this to link a line back to the ledger.
    """

    movement_id = serializers.UUIDField(source="id", read_only=True)
    article = ArticleRefSerializer(read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "movement_id",
            "article",
            "quantity",
            "quantity_before",
            "quantity_after",
            "unit_cost",
        ]


class StockTransactionDetailSerializer(StockTransactionSerializer):
    """The frontend's `StockTransactionDetail` — the list shape plus lines."""

    lines = serializers.SerializerMethodField()

    class Meta(StockTransactionSerializer.Meta):
        fields = StockTransactionSerializer.Meta.fields + ["lines"]

    def get_lines(self, obj):
        # Oldest first, with `id` as the tiebreaker: SQLite can give two
        # movements written in one transaction the same microsecond, and the
        # frontend renders these in submission order.
        movements = obj.lines.select_related("article").order_by("created_at", "id")
        return StockTransactionLineSerializer(movements, many=True).data
