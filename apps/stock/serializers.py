from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.catalogue.models import Article
from apps.catalogue.serializers import ArticleRefSerializer
from apps.stock.models import StockMovement


class StockMovementSerializer(serializers.ModelSerializer):
    """The frontend's `StockMovement`."""

    article = ArticleRefSerializer(read_only=True)
    article_id = serializers.UUIDField(source="article.id", read_only=True)
    site_id = serializers.UUIDField(source="site.id", read_only=True)
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    # Reads the model's `transaction_id` attname directly; DRF renders a
    # None attribute as null without help.
    transaction_id = serializers.UUIDField(read_only=True)
    # No column yet. Sub-project 4 adds `sale` and swaps this line. The key
    # must be present now because the frontend's StockMovement type requires
    # it.
    sale_id = serializers.SerializerMethodField()

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

    def get_sale_id(self, obj) -> None:
        return None


class MovementCreateSerializer(serializers.Serializer):
    """The frontend's `MovementCreateDto`.

    A plain Serializer, not a ModelSerializer: the write shape and the read
    shape genuinely differ — `quantity` means a target rather than a delta on
    an ADJUSTMENT, and `quantityBefore` / `quantityAfter` are derived by
    `apply_movement`, never supplied.
    """

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
